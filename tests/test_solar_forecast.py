import asyncio
import sys
import types
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_module():
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    storage = types.ModuleType("homeassistant.helpers.storage")
    util = types.ModuleType("homeassistant.util")
    dt_module = types.ModuleType("homeassistant.util.dt")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    core.EVENT_STATE_CHANGED = "state_changed"
    core.Event = object
    fixed_now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    dt_module.now = lambda: fixed_now
    dt_module.as_local = lambda value: value

    class Store:
        def __init__(self, *args):
            self.data = None

        async def async_load(self):
            return self.data

        async def async_save(self, data):
            self.data = data

    storage.Store = Store
    helpers.storage = storage
    helpers.entity_registry = entity_registry
    util.dt = dt_module
    homeassistant.core = core
    homeassistant.helpers = helpers
    homeassistant.util = util
    modules = {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_module,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    previous_package = sys.modules.get("custom_components.elrakning")
    sys.modules.update(modules)
    package = types.ModuleType("custom_components.elrakning")
    package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "elrakning")]
    sys.modules["custom_components.elrakning"] = package
    path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "solar_forecast.py"
    spec = spec_from_file_location("custom_components.elrakning.solar_forecast", path)
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for name, original in previous.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    if previous_package is None:
        sys.modules.pop("custom_components.elrakning", None)
    else:
        sys.modules["custom_components.elrakning"] = previous_package
    return module, fixed_now


solar_forecast, FIXED_NOW = _load_module()


def _state(value, unit, name):
    return types.SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit, "friendly_name": name},
    )


class _Bus:
    def __init__(self):
        self.listener = None
        self.events = []

    def async_listen(self, event_type, listener):
        self.listener = listener
        return lambda: None

    def async_fire(self, event_type, data=None):
        self.events.append((event_type, data))


class _States:
    def __init__(self, states):
        self.states = states

    def get(self, entity_id):
        return self.states.get(entity_id)


class _ConfigEntries:
    def __init__(self, entries):
        self.entries = entries

    def async_entries(self, domain):
        return self.entries if domain == "forecast_solar" else []


class _Hass:
    def __init__(self, states, entries, registry):
        self.states = _States(states)
        self.config_entries = _ConfigEntries(entries)
        self.bus = _Bus()
        self.data = {}
        solar_forecast.er.async_get = lambda hass: registry


class ForecastSolarTests(unittest.TestCase):
    def _manager(self, states, registry_entries, entry_count=1):
        entries = [types.SimpleNamespace(entry_id=f"forecast-{index}") for index in range(entry_count)]
        hass = _Hass(states, entries, types.SimpleNamespace(entities={entry.entity_id: entry for entry in registry_entries}))
        return hass, solar_forecast.SolarForecastManager(hass)

    def test_units_normalize_energy_and_power(self):
        self.assertEqual(solar_forecast.normalize_forecast_value(_state(1200, "Wh", "energy production today"), "today_kwh"), 1.2)
        self.assertEqual(solar_forecast.normalize_forecast_value(_state(2, "MW", "power production now"), "power_now_kw"), 2000)
        self.assertEqual(solar_forecast._role("estimated power production next hour"), "power_next_hour_kw")
        self.assertEqual(solar_forecast.normalize_forecast_value(_state(1500, "W", "power production next hour"), "power_next_hour_kw"), 1.5)
        self.assertIsNone(solar_forecast.normalize_forecast_value(_state("unknown", "kWh", "energy production today"), "today_kwh"))

    def test_official_translation_keys_are_discovered(self):
        states = {
            "sensor.energy_current_hour": _state(1, "kWh", "Energy current hour"),
            "sensor.energy_next_hour": _state(2, "kWh", "Energy next hour"),
            "sensor.power_production_next_12hours": _state(1200, "W", "Power production next 12 hours"),
            "sensor.power_production_next_24hours": _state(2400, "W", "Power production next 24 hours"),
        }
        registry = [
            types.SimpleNamespace(
                entity_id=entity_id,
                config_entry_id="forecast-0",
                unique_id=entity_id,
                original_name=state.attributes["friendly_name"],
                translation_key=entity_id.removeprefix("sensor."),
            )
            for entity_id, state in states.items()
        ]
        hass, manager = self._manager(states, registry)
        asyncio.run(manager.async_load())
        public = manager.public_state()
        self.assertEqual(public["this_hour_kwh"], 1)
        self.assertEqual(public["next_hour_kwh"], 2)
        self.assertEqual(public["power_next_12_hours_kw"], 1.2)
        self.assertEqual(public["power_next_24_hours_kw"], 2.4)

    def test_single_source_discovers_facts_and_captures_baselines(self):
        states = {
            "sensor.energy_production_today": _state(5, "kWh", "Estimated energy production today"),
            "sensor.energy_production_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
        }
        registry = [
            types.SimpleNamespace(entity_id=entity_id, config_entry_id="forecast-0", unique_id=entity_id, original_name=state.attributes["friendly_name"], translation_key=None)
            for entity_id, state in states.items()
        ]
        hass, manager = self._manager(states, registry)
        asyncio.run(manager.async_load())
        public = manager.public_state()
        self.assertTrue(public["available"])
        self.assertEqual(public["today_kwh"], 5)
        self.assertEqual(public["tomorrow_kwh"], 12)
        self.assertEqual(public["baselines"], {"2026-08-29": 5, "2026-08-30": 12})
        self.assertTrue(any(event[0] == solar_forecast.UPDATE_EVENT for event in hass.bus.events))

    def test_tomorrow_updates_but_today_baseline_is_frozen(self):
        states = {
            "sensor.energy_production_today": _state(5, "kWh", "Estimated energy production today"),
            "sensor.energy_production_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
        }
        registry = [
            types.SimpleNamespace(entity_id=entity_id, config_entry_id="forecast-0", unique_id=entity_id, original_name=state.attributes["friendly_name"], translation_key=None)
            for entity_id, state in states.items()
        ]
        hass, manager = self._manager(states, registry)
        asyncio.run(manager.async_load())
        states["sensor.energy_production_tomorrow"] = _state(13, "kWh", "Estimated energy production tomorrow")
        asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.energy_production_tomorrow"})))
        states["sensor.energy_production_today"] = _state(6, "kWh", "Estimated energy production today")
        asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.energy_production_today"})))
        self.assertEqual(manager.public_state()["baselines"]["2026-08-30"], 13)
        self.assertEqual(manager.public_state()["baselines"]["2026-08-29"], 5)

    def test_multiple_sources_are_unavailable(self):
        hass, manager = self._manager({}, [], entry_count=2)
        asyncio.run(manager.async_load())
        self.assertFalse(manager.public_state()["available"])

    def test_missing_site_store_does_not_migrate_previous_site_baselines(self):
        hass, manager = self._manager({}, [])
        manager._site_id = "site-a"
        manager._site_context_enabled = True
        manager._baselines = {"2026-08-29": {"forecast_kwh": 5}}

        class EmptyStore:
            async def async_save(self, _data):
                pass

        async def load_site_store(*_args, **_kwargs):
            return EmptyStore(), None

        original = solar_forecast.async_load_site_store
        solar_forecast.async_load_site_store = load_site_store
        try:
            asyncio.run(manager.async_apply_site_context("site-b", {"entities": {}}))
        finally:
            solar_forecast.async_load_site_store = original

        self.assertEqual(manager._site_id, "site-b")
        self.assertEqual(manager.public_state()["baselines"], {})

    def test_existing_site_store_is_loaded_without_cross_site_copy(self):
        hass, manager = self._manager({}, [])

        class ExistingStore:
            async def async_save(self, _data):
                pass

        async def load_site_store(*_args, **_kwargs):
            return ExistingStore(), {"days": {"2026-08-30": {"forecast_kwh": 12}}}

        original = solar_forecast.async_load_site_store
        solar_forecast.async_load_site_store = load_site_store
        try:
            asyncio.run(manager.async_apply_site_context("site-b", {"entities": {}}))
        finally:
            solar_forecast.async_load_site_store = original

        self.assertEqual(manager.public_state()["baselines"], {"2026-08-30": 12})


    def test_background_baseline_capture_continues_for_inactive_enabled_site(self):
        states = {
            "sensor.vik_today": _state(5, "kWh", "Estimated energy production today"),
            "sensor.vik_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
        }
        hass, _manager = self._manager(states, [])
        targets = [{
            "site_id": "site-vik",
            "binding": {
                "config_entry_id": "forecast-entry",
                "binding_fingerprint": "binding-v1",
                "entities": {"today_kwh": "sensor.vik_today", "tomorrow_kwh": "sensor.vik_tomorrow"},
            },
        }]
        manager = solar_forecast.SolarForecastManager(
            hass, collection_targets_getter=lambda: targets
        )
        manager._site_context_enabled = True
        manager._site_id = None
        stores = {}

        class SiteStore:
            def __init__(self, site_id):
                self.site_id = site_id

            async def async_save(self, data):
                stores[self.site_id] = data

        async def load_site_store(_hass, _key, _version, site_id, *_args):
            return SiteStore(site_id), stores.get(site_id)

        original = solar_forecast.async_load_site_store
        solar_forecast.async_load_site_store = load_site_store
        try:
            asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.vik_tomorrow"})))
        finally:
            solar_forecast.async_load_site_store = original

        days = stores["site-vik"]["days"]
        self.assertEqual(days["2026-08-29"]["forecast_kwh"], 5)
        self.assertEqual(days["2026-08-29"]["capture_type"], "first_today")
        self.assertEqual(days["2026-08-30"]["forecast_kwh"], 12)
        self.assertEqual(days["2026-08-30"]["capture_type"], "day_ahead")
        self.assertEqual(days["2026-08-30"]["site_id"], "site-vik")
        self.assertEqual(
            days["2026-08-30"]["source_generation_id"],
            solar_forecast.source_generation_id("site-vik", targets[0]["binding"]),
        )
        self.assertIsNone(manager._site_id)
        self.assertEqual(manager._entities, {})

    def test_background_capture_has_no_target_and_no_store_write_without_binding(self):
        hass, _manager = self._manager({}, [])
        manager = solar_forecast.SolarForecastManager(
            hass, collection_targets_getter=lambda: []
        )
        calls = []

        async def load_site_store(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("no site store should be opened without a target")

        original = solar_forecast.async_load_site_store
        solar_forecast.async_load_site_store = load_site_store
        try:
            result = asyncio.run(manager.async_capture_collection_baselines())
        finally:
            solar_forecast.async_load_site_store = original

        self.assertEqual(result["target_count"], 0)
        self.assertEqual(result["written"], 0)
        self.assertEqual(calls, [])

    def test_background_first_today_is_frozen_and_startup_does_not_reconstruct_yesterday(self):
        states = {
            "sensor.vik_today": _state(5, "kWh", "Estimated energy production today"),
            "sensor.vik_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
        }
        hass, _manager = self._manager(states, [])
        targets = [{
            "site_id": "site-vik",
            "binding": {"entities": {"today_kwh": "sensor.vik_today", "tomorrow_kwh": "sensor.vik_tomorrow"}},
        }]
        manager = solar_forecast.SolarForecastManager(hass, collection_targets_getter=lambda: targets)
        stores = {}

        class SiteStore:
            async def async_save(self, data):
                stores["site-vik"] = data

        async def load_site_store(*_args, **_kwargs):
            return SiteStore(), stores.get("site-vik")

        original = solar_forecast.async_load_site_store
        solar_forecast.async_load_site_store = load_site_store
        try:
            asyncio.run(manager.async_capture_collection_baselines())
            states["sensor.vik_today"] = _state(9, "kWh", "Estimated energy production today")
            states["sensor.vik_tomorrow"] = _state(13, "kWh", "Estimated energy production tomorrow")
            asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.vik_today"})))
        finally:
            solar_forecast.async_load_site_store = original

        days = stores["site-vik"]["days"]
        self.assertNotIn("2026-08-28", days)
        self.assertEqual(days["2026-08-29"]["forecast_kwh"], 5)
        self.assertEqual(days["2026-08-29"]["capture_type"], "first_today")
        self.assertEqual(days["2026-08-30"]["forecast_kwh"], 13)
        self.assertEqual(days["2026-08-30"]["capture_type"], "day_ahead")

    def test_background_rebinding_ignores_old_entity_and_uses_new_entity(self):
        states = {
            "sensor.old_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
            "sensor.new_tomorrow": _state(20, "kWh", "Estimated energy production tomorrow"),
        }
        hass, _manager = self._manager(states, [])
        targets = [{"site_id": "site-vik", "binding": {"entities": {"tomorrow_kwh": "sensor.old_tomorrow"}}}]
        manager = solar_forecast.SolarForecastManager(hass, collection_targets_getter=lambda: targets)
        stores = {}

        class SiteStore:
            async def async_save(self, data):
                stores["site-vik"] = data

        async def load_site_store(*_args, **_kwargs):
            return SiteStore(), stores.get("site-vik")

        original = solar_forecast.async_load_site_store
        solar_forecast.async_load_site_store = load_site_store
        try:
            asyncio.run(manager.async_capture_collection_baselines())
            targets[0] = {"site_id": "site-vik", "binding": {"entities": {"tomorrow_kwh": "sensor.new_tomorrow"}}}
            before = dict(stores["site-vik"]["days"]["2026-08-30"])
            asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.old_tomorrow"})))
            self.assertEqual(stores["site-vik"]["days"]["2026-08-30"], before)
            asyncio.run(manager._async_state_changed(types.SimpleNamespace(data={"entity_id": "sensor.new_tomorrow"})))
        finally:
            solar_forecast.async_load_site_store = original

        self.assertEqual(stores["site-vik"]["days"]["2026-08-30"]["forecast_kwh"], 20)

    def test_site_baseline_reader_is_explicit_and_does_not_change_active_context(self):
        hass, manager = self._manager({}, [])
        manager._site_id = "site-fisk"
        manager._entities = {"today_kwh": "sensor.fisk"}
        cached = {
            "site-vik": {"days": {"2026-08-30": {"forecast_kwh": 12, "capture_type": "day_ahead"}}},
        }

        class SiteStore:
            async def async_save(self, _data):
                pass

        async def load_site_store(_hass, _key, _version, site_id, *_args):
            return SiteStore(), cached.get(site_id)

        original = solar_forecast.async_load_site_store
        solar_forecast.async_load_site_store = load_site_store
        try:
            item = asyncio.run(manager.async_site_baseline_record("site-vik", "2026-08-30"))
        finally:
            solar_forecast.async_load_site_store = original

        self.assertEqual(item["forecast_kwh"], 12)
        self.assertEqual(manager._site_id, "site-fisk")
        self.assertEqual(manager._entities, {"today_kwh": "sensor.fisk"})

    def test_context_switch_waits_for_baseline_store_io_and_keeps_site_context(self):
        states = {
            "sensor.vik_today": _state(5, "kWh", "Estimated energy production today"),
            "sensor.vik_tomorrow": _state(12, "kWh", "Estimated energy production tomorrow"),
        }
        hass, _manager = self._manager(states, [])
        manager = solar_forecast.SolarForecastManager(
            hass,
            collection_targets_getter=lambda: [{
                "site_id": "site-vik",
                "binding": {"entities": {"today_kwh": "sensor.vik_today", "tomorrow_kwh": "sensor.vik_tomorrow"}},
            }],
        )
        stores = {}
        entered = asyncio.Event()
        release = asyncio.Event()

        class SiteStore:
            def __init__(self, site_id):
                self.site_id = site_id

            async def async_save(self, data):
                stores[self.site_id] = data

        async def load_site_store(_hass, _key, _version, site_id, *_args):
            if site_id == "site-vik" and not entered.is_set():
                entered.set()
                await release.wait()
            return SiteStore(site_id), stores.get(site_id)

        original = solar_forecast.async_load_site_store

        async def scenario():
            solar_forecast.async_load_site_store = load_site_store
            try:
                capture = asyncio.create_task(manager.async_capture_collection_baselines())
                await entered.wait()
                switch = asyncio.create_task(manager.async_apply_site_context("site-fisk", {"entities": {"today_kwh": "sensor.fisk_today"}}))
                await asyncio.sleep(0)
                self.assertFalse(switch.done())
                release.set()
                await asyncio.gather(capture, switch)
            finally:
                solar_forecast.async_load_site_store = original

        asyncio.run(scenario())
        self.assertEqual(manager._site_id, "site-fisk")
        self.assertEqual(manager._entities, {"today_kwh": "sensor.fisk_today"})
        self.assertIn("site-vik", stores)
        self.assertNotIn("site-fisk", stores)

    def test_baseline_capture_waits_for_context_restore_lock(self):
        hass, manager = self._manager({}, [])
        entered = asyncio.Event()
        release = asyncio.Event()
        stores = {}

        class SiteStore:
            async def async_save(self, data):
                stores["site-vik"] = data

        async def load_site_store(_hass, _key, _version, site_id, *_args):
            if site_id == "site-fisk" and not entered.is_set():
                entered.set()
                await release.wait()
            return SiteStore(), None

        original = solar_forecast.async_load_site_store

        async def scenario():
            solar_forecast.async_load_site_store = load_site_store
            try:
                restore = asyncio.create_task(manager.async_apply_site_context("site-fisk", {"entities": {}}))
                await entered.wait()
                manager._collection_targets_getter = lambda: [{"site_id": "site-vik", "binding": {"entities": {}}}]
                capture = asyncio.create_task(manager.async_capture_collection_baselines())
                await asyncio.sleep(0)
                self.assertFalse(capture.done())
                release.set()
                await asyncio.gather(restore, capture)
            finally:
                solar_forecast.async_load_site_store = original

        asyncio.run(scenario())
        self.assertEqual(manager._site_id, "site-fisk")
        self.assertNotIn("site-vik", stores)


if __name__ == "__main__":
    unittest.main()
