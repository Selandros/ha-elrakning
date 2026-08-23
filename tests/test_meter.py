import sys
import types
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_meter_module():
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    storage = types.ModuleType("homeassistant.helpers.storage")
    device_registry.async_get = lambda hass: None
    entity_registry.async_get = lambda hass: None
    core.EVENT_STATE_CHANGED = "state_changed"
    core.Event = object
    core.State = object
    core.valid_entity_id = lambda value: isinstance(value, str) and value.startswith("sensor.") and len(value) > len("sensor.")
    util = types.ModuleType("homeassistant.util")
    dt_util = types.ModuleType("homeassistant.util.dt")
    dt_util.now = lambda: datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    dt_util.start_of_local_day = lambda value: value.replace(hour=0, minute=0, second=0, microsecond=0)

    class Store:
        def __init__(self, *args):
            self.data = None

        async def async_load(self):
            return self.data

        async def async_save(self, data):
            self.data = data

        async def async_remove(self):
            self.data = None

    storage.Store = Store
    helpers.device_registry = device_registry
    helpers.entity_registry = entity_registry
    helpers.storage = storage
    homeassistant.core = core
    homeassistant.helpers = helpers
    homeassistant.util = util
    util.dt = dt_util
    mocked_modules = {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.storage": storage,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_util,
    }
    previous = {name: sys.modules.get(name) for name in mocked_modules}
    sys.modules.update(mocked_modules)
    path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "meter.py"
    spec = spec_from_file_location("meter", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, original in previous.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    return module


meter = _load_meter_module()


def _hass(*entity_ids):
    states = {
        entity_id: types.SimpleNamespace(
            state="0",
            attributes={"unit_of_measurement": "W"},
        )
        for entity_id in entity_ids
    }
    async def async_add_executor_job(function, *args, **kwargs):
        return function(*args, **kwargs)

    return types.SimpleNamespace(
        states=types.SimpleNamespace(async_all=lambda domain: [], get=states.get),
        bus=types.SimpleNamespace(async_listen=lambda *args: lambda: None),
        async_add_executor_job=async_add_executor_job,
    )


class MeterTests(unittest.IsolatedAsyncioTestCase):
    def test_positive_power_is_import(self):
        state = types.SimpleNamespace(
            state="2400",
            attributes={"unit_of_measurement": "W"},
            last_updated=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(
            meter.normalize_power_state(state),
            {
                "timestamp": "2026-08-23T12:00:00+00:00",
                "import_kw": 2.4,
                "export_kw": 0,
            },
        )

    def test_negative_power_is_export(self):
        state = types.SimpleNamespace(
            state="-1.2",
            attributes={"unit_of_measurement": "kW"},
            last_updated=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )
        point = meter.normalize_power_state(state)
        self.assertEqual(point["import_kw"], 0)
        self.assertEqual(point["export_kw"], 1.2)

    def test_zero_power_has_no_direction(self):
        state = types.SimpleNamespace(
            state="0",
            attributes={"unit_of_measurement": "W"},
            last_updated=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(meter.normalize_power_state(state)["import_kw"], 0)
        self.assertEqual(meter.normalize_power_state(state)["export_kw"], 0)

    def test_invalid_power_is_ignored(self):
        state = types.SimpleNamespace(
            state="unavailable",
            attributes={"unit_of_measurement": "W"},
            last_updated=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )
        self.assertIsNone(meter.normalize_power_state(state))

    async def test_power_history_is_chronological_and_semantic(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        history.get_significant_states = lambda *args, **kwargs: {
            "sensor.power": [
                types.SimpleNamespace(
                    state="-500",
                    attributes={"unit_of_measurement": "W"},
                    last_updated=datetime(2026, 8, 23, 11, tzinfo=timezone.utc),
                ),
                types.SimpleNamespace(
                    state="1.5",
                    attributes={"unit_of_measurement": "kW"},
                    last_updated=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
                ),
            ]
        }
        recorder.history = history
        previous = {
            name: sys.modules.get(name)
            for name in ("homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history")
        }
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        sys.modules.update({
            "homeassistant.components": components,
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.history": history,
        })
        try:
            hass = _hass("sensor.power")
            manager = meter.MeterManager(hass)
            await manager.async_save_mapping({"power_entity": "sensor.power"})
            result = await manager.async_power_history()
        finally:
            for name, original in previous.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original
        self.assertEqual([point["timestamp"] for point in result["points"]], [
            "2026-08-23T10:00:00+00:00",
            "2026-08-23T11:00:00+00:00",
        ])
        self.assertEqual(result["points"][0]["import_kw"], 1.5)
        self.assertEqual(result["points"][1]["export_kw"], 0.5)

    async def test_save_without_selected_meter_clears_configuration(self):
        hass = _hass()
        manager = meter.MeterManager(hass)
        state = await manager.async_save_mapping({})
        self.assertFalse(state["configured"])

    async def test_selected_mapping_is_saved(self):
        hass = _hass("sensor.power")
        manager = meter.MeterManager(hass)
        state = await manager.async_save_mapping({"power_entity": "sensor.power"})
        self.assertEqual(state["power_entity"], "sensor.power")
        self.assertTrue(state["configured"])

    async def test_partial_mapping_saves_only_selected_entities(self):
        hass = _hass("sensor.import")
        manager = meter.MeterManager(hass)
        state = await manager.async_save_mapping({
            "energy_import_entity": "sensor.import",
            "energy_export_entity": "",
            "power_entity": "",
        })
        self.assertEqual(state["energy_import_entity"], "sensor.import")
        self.assertIsNone(state["energy_export_entity"])
        self.assertIsNone(state["power_entity"])

    async def test_export_only_mapping_saves_export_entity(self):
        hass = _hass("sensor.export")
        manager = meter.MeterManager(hass)
        state = await manager.async_save_mapping({"energy_export_entity": "sensor.export"})
        self.assertTrue(state["configured"])
        self.assertEqual(state["energy_export_entity"], "sensor.export")
        self.assertIsNone(state["energy_import_entity"])
        self.assertIsNone(state["power_entity"])

    async def test_import_and_export_mapping_saves_both_entities(self):
        hass = _hass("sensor.import", "sensor.export")
        manager = meter.MeterManager(hass)
        state = await manager.async_save_mapping({
            "energy_import_entity": "sensor.import",
            "energy_export_entity": "sensor.export",
        })
        self.assertTrue(state["configured"])
        self.assertEqual(state["energy_import_entity"], "sensor.import")
        self.assertEqual(state["energy_export_entity"], "sensor.export")
        self.assertIsNone(state["power_entity"])

    async def test_empty_mapping_clears_meter(self):
        hass = _hass()
        manager = meter.MeterManager(hass)
        manager.mapping = {
            "power_entity": "sensor.power",
            "energy_import_entity": "sensor.import",
            "energy_export_entity": None,
        }
        state = await manager.async_save_mapping({
            "power_entity": "",
            "energy_import_entity": "",
            "energy_export_entity": "",
        })
        self.assertFalse(state["configured"])
        self.assertIsNone(state["power_entity"])
        self.assertIsNone(state["energy_import_entity"])
        self.assertIsNone(state["energy_export_entity"])

    async def test_signed_power_is_saved_without_role_inference(self):
        hass = _hass("sensor.signed_power")
        manager = meter.MeterManager(hass)
        await manager.async_save_mapping({
            "power_entity": "sensor.signed_power",
        })
        self.assertEqual(manager.mapping["power_entity"], "sensor.signed_power")

    async def test_clear_resets_all_meter_state(self):
        hass = _hass()
        manager = meter.MeterManager(hass)
        manager.mapping["power_entity"] = "sensor.power"
        state = await manager.async_clear()
        self.assertFalse(state["configured"])
        self.assertTrue(all(value is None for value in manager.mapping.values()))

    async def test_save_emits_diagnostics(self):
        hass = _hass("sensor.power")
        events = []

        async def diagnostic(level, component, event, message):
            events.append((level, component, event))

        manager = meter.MeterManager(hass, diagnostic)
        await manager.async_save_mapping({"power_entity": "sensor.power"})
        self.assertEqual(
            [event for _, _, event in events],
            [
                "meter_mapping_received",
                "meter_validation_success",
                "meter_store_write_success",
                "meter_store_current_state",
            ],
        )

    async def test_empty_save_emits_success_diagnostics(self):
        hass = _hass()
        events = []

        async def diagnostic(level, component, event, message):
            events.append((level, component, event))

        manager = meter.MeterManager(hass, diagnostic)
        await manager.async_save_mapping({})
        self.assertEqual(events[-1], ("INFO", "meter", "meter_store_current_state"))

    async def test_missing_entity_is_rejected_without_overwriting_mapping(self):
        hass = _hass("sensor.existing")
        events = []

        async def diagnostic(level, component, event, message):
            events.append((level, component, event))

        manager = meter.MeterManager(hass, diagnostic)
        await manager.async_save_mapping({"power_entity": "sensor.existing"})

        with self.assertRaisesRegex(ValueError, "entity_not_found:power_entity"):
            await manager.async_save_mapping({"power_entity": "sensor.missing"})

        self.assertEqual(manager.mapping["power_entity"], "sensor.existing")
        self.assertEqual(events[-1], ("ERROR", "meter", "meter_save_failed"))

    async def test_invalid_entity_format_is_rejected(self):
        hass = _hass()
        events = []

        async def diagnostic(level, component, event, message):
            events.append((level, component, event))

        manager = meter.MeterManager(hass, diagnostic)

        with self.assertRaisesRegex(ValueError, "invalid_entity_id:power_entity"):
            await manager.async_save_mapping({"power_entity": "not_an_entity"})

        self.assertFalse((await manager.async_state())["configured"])
        self.assertEqual(events[-1], ("ERROR", "meter", "meter_save_failed"))

if __name__ == "__main__":
    unittest.main()
