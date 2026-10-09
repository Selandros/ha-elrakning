"""Bounded, dependency-free shadow transport for the Elräkning App."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import hmac
import json
import os
from typing import Any

try:
    from .app_contract import AppContractError, validate_state_snapshot
except ModuleNotFoundError:
    from custom_components.elrakning.app_contract import AppContractError, validate_state_snapshot


MAX_BODY_BYTES = 256 * 1024
MAX_SITES = 8
MAX_SNAPSHOTS_PER_SITE = 4


class ShadowState:
    """Keep only a bounded latest-snapshot buffer; no canonical writes occur."""

    def __init__(self) -> None:
        self._snapshots: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

    def accept(self, snapshot: dict[str, Any]) -> int:
        site_id = str(snapshot["site_id"])
        bucket = self._snapshots.pop(site_id, [])
        bucket.append(snapshot)
        self._snapshots[site_id] = bucket[-MAX_SNAPSHOTS_PER_SITE:]
        while len(self._snapshots) > MAX_SITES:
            self._snapshots.popitem(last=False)
        return len(self._snapshots[site_id])


def _response(status: int, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    reason = "OK" if status < 400 else "Bad Request"
    return (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: application/json\r\n"
        "Cache-Control: no-store\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, str, dict[str, str], bytes]:
    header_bytes = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2.0)
    if len(header_bytes) > 16 * 1024:
        raise ValueError("headers_too_large")
    lines = header_bytes.decode("latin-1").split("\r\n")
    method, path, _ = lines[0].split(" ", 2)
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", "0"))
    if content_length < 0 or content_length > MAX_BODY_BYTES:
        raise ValueError("body_too_large")
    body = await asyncio.wait_for(reader.readexactly(content_length), timeout=2.0)
    return method, path, headers, body


def _authorized(headers: dict[str, str], token: str) -> bool:
    supplied = headers.get("authorization", "")
    expected = f"Bearer {token}"
    return bool(token) and hmac.compare_digest(supplied, expected)


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: ShadowState,
    token: str,
) -> None:
    try:
        method, path, headers, body = await _read_request(reader)
        if not _authorized(headers, token):
            writer.write(_response(401, {"available": False, "reason": "unauthorized"}))
        elif method == "GET" and path == "/v1/health/live":
            writer.write(_response(200, {"live": True, "contract_version": 1}))
        elif method == "GET" and path == "/v1/health/ready":
            writer.write(_response(200, {
                "ready": True,
                "shadow_mode": True,
                "source_of_truth": "core",
                "writes_enabled": False,
                "physical_control": False,
                "contract_version": 1,
            }))
        elif method == "POST" and path == "/v1/snapshots":
            snapshot = validate_state_snapshot(json.loads(body.decode("utf-8")))
            count = state.accept(snapshot)
            writer.write(_response(202, {
                "accepted": True,
                "site_id": snapshot["site_id"],
                "buffered_snapshot_count": count,
                "source_of_truth": "core",
                "physical_control": False,
            }))
        else:
            writer.write(_response(404, {"available": False, "reason": "not_found"}))
    except (asyncio.TimeoutError, ValueError, json.JSONDecodeError, AppContractError):
        writer.write(_response(400, {"accepted": False, "reason": "invalid_request"}))
    except Exception:
        writer.write(_response(500, {"accepted": False, "reason": "internal_error"}))
    finally:
        try:
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()


async def _serve() -> None:
    # The add-on has no host port mapping; this bind is internal to its network.
    host = os.getenv("ELRAKNING_APP_BIND_HOST", "0.0.0.0")
    port = int(os.getenv("ELRAKNING_APP_PORT", "8099"))
    token = os.getenv("ELRAKNING_APP_TOKEN", "")
    if not token:
        raise RuntimeError("ELRAKNING_APP_TOKEN is required")
    state = ShadowState()
    server = await asyncio.start_server(
        lambda reader, writer: _handle(reader, writer, state, token), host, port
    )
    async with server:
        await server.serve_forever()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
