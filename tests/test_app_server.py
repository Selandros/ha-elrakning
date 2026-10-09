import asyncio
import json

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub


install_homeassistant_stubs()
install_elrakning_package_stub()

from app.elrakning_app.server import MAX_SITES, ShadowState, _handle


def _snapshot(site_id: str) -> dict:
    return {
        "contract_version": 1,
        "site_id": site_id,
        "source_generation_id": "generation-a",
        "captured_at": "2026-10-09T10:00:02Z",
        "decision_context": {"decision_at": "2026-10-09T10:00:00Z"},
        "entity_source_identity": {"logical_role": "grid.power/import", "entity": "sensor.test"},
        "value": 1.25,
        "unit": "kW",
        "sign_convention": "positive_import",
        "observed_at": "2026-10-09T09:59:00Z",
        "known_at": "2026-10-09T09:59:30Z",
        "quality": {"status": "good"},
        "status": "available",
    }


class _Writer:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, value):
        self.data.extend(value)

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


class _Reader:
    def __init__(self, request: bytes):
        self.request = request

    async def readuntil(self, _separator):
        return self.request.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"

    async def readexactly(self, length):
        body = self.request.split(b"\r\n\r\n", 1)[1]
        return body[:length]


def test_snapshot_ingress_is_authenticated_and_bounded():
    async def run():
        state = ShadowState()
        body = json.dumps(_snapshot("site-a"), separators=(",", ":")).encode()
        request = (
            b"POST /v1/snapshots HTTP/1.1\r\n"
            b"Authorization: Bearer test-token\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        writer = _Writer()
        await _handle(_Reader(request), writer, state, "test-token")
        response = bytes(writer.data)
        assert response.startswith(b"HTTP/1.1 202")
        assert b'"accepted":true' in response

        for index in range(MAX_SITES + 2):
            state.accept(_snapshot(f"site-{index}"))
        assert len(state._snapshots) == MAX_SITES

    asyncio.run(run())


def test_snapshot_ingress_rejects_missing_auth_without_storing():
    async def run():
        state = ShadowState()
        writer = _Writer()
        await _handle(_Reader(b"GET /v1/health/live HTTP/1.1\r\n\r\n"), writer, state, "test-token")
        assert bytes(writer.data).startswith(b"HTTP/1.1 401")
        assert not state._snapshots

    asyncio.run(run())
