import unittest
from types import SimpleNamespace

from tests._elrakning_test_bootstrap import (
    install_elrakning_package_stub,
    install_homeassistant_stubs,
    install_optional_dependency_stubs,
)

install_elrakning_package_stub()
install_homeassistant_stubs()
install_optional_dependency_stubs()

from custom_components.elrakning.solar_open_meteo import (
    SolarOpenMeteoManager,
    build_open_meteo_targets,
    normalize_open_meteo_payload,
    normalize_source_timestamp,
    _location_fingerprint,
    _parse_fetched_at,
    _parse_hourly,
    compass_to_open_meteo_azimuth,
)


async def _raising_load():
    raise RuntimeError("store failure")


async def _empty_state():
    return {}


class SolarOpenMeteoTests(unittest.TestCase):
    def _site_config(self, site_id="site-a", location=None):
        return {
            site_id: {
                "collection_enabled": True,
                "location": location or {
                    "latitude": 62.20646687401988,
                    "longitude": 17.490212917327884,
                    "timezone": "Europe/Stockholm",
                    "verification_state": "verified",
                    "provenance": "test",
                    "location_fingerprint": _location_fingerprint(62.20646687401988, 17.490212917327884, "Europe/Stockholm"),
                },
                "bindings": {"open_meteo": {"source": "open_meteo_global_tilted_irradiance", "binding_fingerprint": "binding-a"}},
                "power": {
                    "solar_entities": ["sensor.pv"],
                    "solar_array_metadata": {
                        "sensor.pv": {"capacity_kwp": 9.45, "tilt_deg": 30, "azimuth_deg": 225}
                    },
                },
            }
        }

    def test_open_meteo_targets_are_site_explicit_and_fail_closed(self):
        targets = build_open_meteo_targets(self._site_config())
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["site_id"], "site-a")
        self.assertEqual(targets[0]["generation_id"].startswith("om-"), True)
        self.assertEqual(build_open_meteo_targets(self._site_config("site-b", {
            "latitude": 62.2, "longitude": 17.4, "timezone": "Europe/Stockholm",
            "verification_state": "unverified",
        })), [])

    def test_open_meteo_source_identity_excludes_provenance_only_changes(self):
        first = build_open_meteo_targets(self._site_config())[0]
        changed = self._site_config()
        changed["site-a"]["power"]["solar_array_metadata"]["sensor.pv"]["capacity_kwp"] = 12
        changed["site-a"]["power"]["solar_entities"] = ["sensor.pv_renamed"]
        changed["site-a"]["power"]["solar_array_metadata"]["sensor.pv_renamed"] = changed["site-a"]["power"]["solar_array_metadata"].pop("sensor.pv")
        second = build_open_meteo_targets(changed)[0]
        self.assertEqual(first["generation_id"], second["generation_id"])
        self.assertNotEqual(first["source_strings"], second["source_strings"])

    def test_open_meteo_timezone_is_generation_identity(self):
        stockholm = build_open_meteo_targets(self._site_config())[0]
        helsinki = self._site_config()
        helsinki["site-a"]["location"]["timezone"] = "Europe/Helsinki"
        helsinki["site-a"]["location"]["location_fingerprint"] = _location_fingerprint(62.20646687401988, 17.490212917327884, "Europe/Helsinki")
        other = build_open_meteo_targets(helsinki)[0]
        self.assertNotEqual(stockholm["generation_id"], other["generation_id"])

    def test_open_meteo_binding_must_identify_source(self):
        config = self._site_config()
        config["site-a"]["bindings"]["open_meteo"]["source"] = "not-open-meteo"
        self.assertEqual(build_open_meteo_targets(config), [])

    def test_open_meteo_timestamp_normalization_rejects_ambiguous_local_time(self):
        self.assertEqual(
            normalize_source_timestamp("2026-09-12T12:00", "Europe/Stockholm").isoformat(),
            "2026-09-12T10:00:00+00:00",
        )
        self.assertIsNone(normalize_source_timestamp("2026-10-25T02:30", "Europe/Stockholm"))

    def test_open_meteo_payload_preserves_negative_raw_gti_and_marks_gaps(self):
        target = build_open_meteo_targets(self._site_config())[0]
        result = normalize_open_meteo_payload(
            {
                "timezone": "Europe/Stockholm",
                "hourly": {
                    "time": ["2026-09-12T12:00", "2026-09-12T13:00", "2026-09-12T14:00"],
                    "global_tilted_irradiance": [-2.5, None, 4.0],
                },
            },
            target,
        )
        self.assertEqual([point["value"] for point in result["points"]], [-2.5, 4.0])
        self.assertEqual(result["quality_status"], "partial")
        self.assertEqual(result["points"][0]["unit"], "W/m²")

    def test_open_meteo_payload_resolves_ordered_autumn_duplicate(self):
        target = build_open_meteo_targets(self._site_config())[0]
        result = normalize_open_meteo_payload(
            {
                "timezone": "Europe/Stockholm",
                "hourly": {
                    "time": ["2026-10-25T01:00", "2026-10-25T02:00", "2026-10-25T02:00", "2026-10-25T03:00"],
                    "global_tilted_irradiance": [1, 2, 3, 4],
                },
            },
            target,
        )
        self.assertEqual(
            [point["valid_at"].isoformat() for point in result["points"]],
            [
                "2026-10-24T23:00:00+00:00",
                "2026-10-25T00:00:00+00:00",
                "2026-10-25T01:00:00+00:00",
                "2026-10-25T02:00:00+00:00",
            ],
        )

    def test_open_meteo_singleton_ambiguous_and_cadence_gap_are_partial(self):
        target = build_open_meteo_targets(self._site_config())[0]
        result = normalize_open_meteo_payload(
            {
                "timezone": "Europe/Stockholm",
                "hourly": {
                    "time": ["2026-10-25T02:00", "2026-10-25T04:00"],
                    "global_tilted_irradiance": [1, 2],
                },
            },
            target,
        )
        self.assertEqual(result["quality_status"], "partial")
        self.assertEqual(len(result["points"]), 1)
        reasons = {gap["reason"] for gap in result["quality"]["gaps"]}
        self.assertIn("ambiguous_timestamp", reasons)
        cadence = normalize_open_meteo_payload(
            {
                "timezone": "Europe/Stockholm",
                "hourly": {
                    "time": ["2026-09-12T12:00", "2026-09-12T14:00"],
                    "global_tilted_irradiance": [1, 2],
                },
            },
            target,
        )
        self.assertIn("cadence_gap", {gap["reason"] for gap in cadence["quality"]["gaps"]})

    def test_open_meteo_duplicate_nonmonotonic_point_is_a_gap_not_total_failure(self):
        target = build_open_meteo_targets(self._site_config())[0]
        result = normalize_open_meteo_payload(
            {
                "timezone": "Europe/Stockholm",
                "hourly": {
                    "time": ["2026-09-12T12:00", "2026-09-12T12:00", "2026-09-12T13:00"],
                    "global_tilted_irradiance": [1, 2, 3],
                },
            },
            target,
        )
        self.assertEqual(len(result["points"]), 2)
        self.assertIn("nonmonotonic_timestamp_sequence", {gap["reason"] for gap in result["quality"]["gaps"]})

    def test_open_meteo_all_invalid_values_are_an_invalid_frame_candidate(self):
        target = build_open_meteo_targets(self._site_config())[0]
        result = normalize_open_meteo_payload(
            {
                "timezone": "Europe/Stockholm",
                "hourly": {
                    "time": ["2026-09-12T12:00", "2026-09-12T13:00"],
                    "global_tilted_irradiance": [None, float("nan")],
                },
            },
            target,
        )
        self.assertEqual(result["points"], [])
        self.assertEqual(result["quality_status"], "invalid")

    def test_open_meteo_location_migration_is_same_site_and_idempotent(self):
        import asyncio
        import custom_components.elrakning.solar_open_meteo as module

        manager = SolarOpenMeteoManager.__new__(SolarOpenMeteoManager)
        manager.hass = SimpleNamespace()
        site_configs = {
            "site-a": {
                "bindings": {"open_meteo": {"source": "open_meteo_global_tilted_irradiance", "installation_fingerprint": "legacy"}},
            },
            "site-b": {"bindings": {}},
        }
        cached = {
            "installation": {
                "latitude": 62.20646687401988,
                "longitude": 17.490212917327884,
                "fingerprint": "legacy",
            },
            "state": {},
            "frame": {"api_metadata": {"timezone": "Europe/Stockholm"}},
        }
        class Identity:
            def __init__(self):
                self.saved = {}
            def collection_site_configs(self):
                return site_configs
            async def async_set_site_location(self, site_id, location):
                if site_id in self.saved:
                    return False
                self.saved[site_id] = location
                return True
        async def load_store(*_args):
            return SimpleNamespace(), cached if _args[-1] == "site-a" else None
        original = module.async_load_site_store
        module.async_load_site_store = load_store
        try:
            identity = Identity()
            self.assertEqual(asyncio.run(manager.async_migrate_site_locations(identity)), 1)
            self.assertEqual(identity.saved["site-a"]["verification_state"], "verified")
            site_configs["site-a"]["location"] = identity.saved["site-a"]
            self.assertEqual(asyncio.run(manager.async_migrate_site_locations(identity)), 0)
            self.assertNotIn("site-b", identity.saved)
        finally:
            module.async_load_site_store = original
    def test_manager_accepts_missing_or_invalid_fetched_at_as_cache_miss(self):
        for value in (None, "not-a-timestamp"):
            self.assertIsNone(_parse_fetched_at(value))

    def test_manager_startup_survives_store_failure(self):
        manager = SolarOpenMeteoManager.__new__(SolarOpenMeteoManager)
        manager.hass = SimpleNamespace(config=SimpleNamespace(latitude=None, longitude=None))
        manager.power_manager = SimpleNamespace(async_state=lambda: _empty_state())
        manager.store = SimpleNamespace(async_load=_raising_load)
        manager._state = {"available": False}
        manager._installation = None
        manager._frame = None
        manager._frame_id = None
        import asyncio
        asyncio.run(manager.async_load())
        self.assertFalse(manager._state["available"])


    def test_compass_azimuth_conversion(self):
        self.assertEqual(compass_to_open_meteo_azimuth(180), 0)
        self.assertEqual(compass_to_open_meteo_azimuth(90), -90)
        self.assertEqual(compass_to_open_meteo_azimuth(270), 90)
        self.assertEqual(compass_to_open_meteo_azimuth(0), 180)
        self.assertEqual(compass_to_open_meteo_azimuth(225), 45)

    def test_gti_is_integrated_from_watts_per_square_meter_to_kwh_per_square_meter(self):
        result = _parse_hourly(
            {"hourly": {"time": ["2026-09-02T12:00", "2026-09-02T13:00"], "global_tilted_irradiance": [500, 250]}},
            {"source_strings": ["PV1"], "peak_power_kwp": 9.45, "tilt_deg": 30, "azimuth_deg": 225},
        )
        self.assertEqual(result["irradiance_kwh_m2"], 0.75)
        self.assertAlmostEqual(result["potential_dc_kwh"], 7.0875)
        self.assertEqual(result["open_meteo_azimuth_deg"], 45)

    def test_invalid_or_empty_response_is_unavailable(self):
        self.assertIsNone(_parse_hourly({}, {"source_strings": [], "peak_power_kwp": 1, "tilt_deg": 30, "azimuth_deg": 180}))

    def test_missing_site_store_clears_previous_site_frame(self):
        manager = SolarOpenMeteoManager.__new__(SolarOpenMeteoManager)
        manager.hass = SimpleNamespace()
        manager._site_id = "site-a"
        manager._context_generation = 0
        manager._request_generation = 0
        manager._installation = {"fingerprint": "site-a"}
        manager._frame = {"installation_fingerprint": "site-a"}
        manager._frame_id = "a"
        manager._state = {"available": True, "site_id": "site-a"}

        class EmptyStore:
            async def async_save(self, _data):
                pass

        async def load_site_store(*_args, **_kwargs):
            return EmptyStore(), None

        import custom_components.elrakning.solar_open_meteo as module
        original = module.async_load_site_store
        module.async_load_site_store = load_site_store
        try:
            import asyncio
            asyncio.run(manager.async_apply_site_context("site-b", {"installation_fingerprint": "site-b"}))
        finally:
            module.async_load_site_store = original

        self.assertEqual(manager._site_id, "site-b")
        self.assertIsNone(manager._frame)
        self.assertFalse(manager._state["available"])

    def test_obsolete_response_does_not_mutate_new_site_context(self):
        import asyncio

        manager = SolarOpenMeteoManager.__new__(SolarOpenMeteoManager)
        manager._site_id = "site-a"
        manager._context_generation = 1
        manager._request_generation = 1
        manager._installation = None
        manager._frame = None
        manager._frame_id = None
        manager._state = {"available": False}

        class Store:
            def __init__(self):
                self.saved = []

            async def async_save(self, data):
                self.saved.append(data)

        store = Store()
        started = asyncio.Event()
        release = asyncio.Event()

        class Response:
            status = 200

            async def __aenter__(self):
                started.set()
                await release.wait()
                return self

            async def __aexit__(self, *_args):
                return None

            async def json(self):
                return {"hourly": {"time": ["2026-09-02T12:00"], "global_tilted_irradiance": [500]}}

        class Session:
            def get(self, *_args, **_kwargs):
                return Response()

        import custom_components.elrakning.solar_open_meteo as module
        original = module.async_get_clientsession
        module.async_get_clientsession = lambda _hass: Session()
        try:
            manager.hass = object()
            context = {
                "site_id": "site-a",
                "context_generation": 1,
                "request_generation": 1,
                "store": store,
            }
            installation = {
                "latitude": 62.0,
                "longitude": 17.0,
                "fingerprint": "site-a",
                "sections": [{
                    "source_strings": ["pv1"],
                    "peak_power_kwp": 1.0,
                    "tilt_deg": 30,
                    "azimuth_deg": 180,
                }],
            }
            async def scenario():
                task = asyncio.create_task(manager._async_fetch(installation, context))
                await started.wait()
                manager._context_generation = 2
                manager._site_id = "site-b"
                release.set()
                await task

            asyncio.run(scenario())
        finally:
            module.async_get_clientsession = original

        self.assertIsNone(manager._frame)
        self.assertEqual(store.saved, [])


if __name__ == "__main__":
    unittest.main()
