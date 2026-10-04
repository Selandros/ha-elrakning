import asyncio
import types
import unittest
from unittest.mock import patch

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)


install_homeassistant_stubs()
install_elrakning_package_stub()
install_optional_dependency_stubs()

from custom_components.elrakning import websocket  # noqa: E402
from custom_components.elrakning.const import DOMAIN  # noqa: E402


class _Connection:
    def __init__(self):
        self.results = []

    def send_result(self, message_id, payload):
        self.results.append((message_id, payload))


class _Hass:
    def __init__(self):
        identity = types.SimpleNamespace(state={
            "active_site_id": "site-a",
            "site_configs": {"site-a": {"location": {"timezone": "Europe/Stockholm"}}},
        })
        self.data = {DOMAIN: {
            "site_identity_manager": identity,
            "canonical_collector": object(),
        }}
        self.config = types.SimpleNamespace(time_zone="Europe/Stockholm")

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


class CanonicalEnergyHistoryFastPathTests(unittest.TestCase):
    def test_exact_local_day_is_returned_for_active_site(self):
        async def run():
            hass = _Hass()
            connection = _Connection()
            captured = {}

            async def build_history(_hass, _identity, _collector, start, end, site_id=None):
                captured["start"] = start
                captured["end"] = end
                captured["site_id"] = site_id
                return {"site_id": "site-a", "series": {"import": [{"value_kw": 0.392}]}}

            with patch.object(websocket, "async_build_energy_history", build_history):
                await websocket.websocket_canonical_energy_history(
                    hass, connection, {"id": 1, "date": "2026-10-04"},
                )
            return connection.results[-1][1], captured

        payload, captured = asyncio.run(run())
        self.assertEqual(payload["success"], True)
        self.assertEqual(payload["site_id"], "site-a")
        self.assertEqual(payload["date"], "2026-10-04")
        self.assertEqual(payload["energy_history"]["series"]["import"][0]["value_kw"], 0.392)
        self.assertEqual(captured["start"].isoformat(), "2026-10-03T22:00:00+00:00")
        self.assertEqual(captured["end"].isoformat(), "2026-10-04T22:00:00+00:00")
        self.assertEqual(captured["site_id"], "site-a")

    def test_concurrent_same_context_uses_one_storage_build(self):
        async def run():
            hass = _Hass()
            first = _Connection()
            second = _Connection()
            started = asyncio.Event()
            release = asyncio.Event()
            calls = 0

            async def build_history(_hass, _identity, _collector, _start, _end, site_id=None):
                nonlocal calls
                calls += 1
                started.set()
                await release.wait()
                return {"site_id": "site-a", "series": {"import": []}}

            with patch.object(websocket, "async_build_energy_history", build_history):
                first_task = asyncio.create_task(websocket.websocket_canonical_energy_history(
                    hass, first, {"id": 1, "date": "2026-10-04"},
                ))
                await started.wait()
                second_task = asyncio.create_task(websocket.websocket_canonical_energy_history(
                    hass, second, {"id": 2, "date": "2026-10-04"},
                ))
                await asyncio.sleep(0)
                release.set()
                await asyncio.gather(first_task, second_task)
            return calls, first.results[-1][1], second.results[-1][1]

        calls, first_payload, second_payload = asyncio.run(run())
        self.assertEqual(calls, 1)
        self.assertEqual(first_payload["success"], True)
        self.assertEqual(second_payload["success"], True)

    def test_invalid_date_fails_closed_without_storage_read(self):
        async def run():
            hass = _Hass()
            connection = _Connection()
            await websocket.websocket_canonical_energy_history(
                hass, connection, {"id": 1, "date": "not-a-date"},
            )
            return connection.results[-1][1]

        self.assertEqual(asyncio.run(run()), {"success": False, "error": "invalid_date"})

    def test_storage_failure_fails_closed(self):
        async def run():
            hass = _Hass()
            connection = _Connection()

            async def fail_history(*_args, **_kwargs):
                raise RuntimeError("storage unavailable")

            with patch.object(websocket, "async_build_energy_history", fail_history):
                await websocket.websocket_canonical_energy_history(
                    hass, connection, {"id": 1, "date": "2026-10-04"},
                )
            return connection.results[-1][1]

        self.assertEqual(asyncio.run(run()), {
            "success": False,
            "error": "canonical_history_unavailable",
            "site_id": "site-a",
        })


if __name__ == "__main__":
    unittest.main()
