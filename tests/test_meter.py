import asyncio
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
            attributes={
                "unit_of_measurement": "kWh" if entity_id in {"sensor.import", "sensor.export"} else "W",
                "device_class": "energy" if entity_id in {"sensor.import", "sensor.export"} else "power",
            },
        )
        for entity_id in entity_ids
    }
    async def async_add_executor_job(function, *args, **kwargs):
        return function(*args, **kwargs)

    recorder = types.SimpleNamespace(async_add_executor_job=async_add_executor_job)
    return types.SimpleNamespace(
        states=types.SimpleNamespace(async_all=lambda domain: [], get=states.get),
        bus=types.SimpleNamespace(async_listen=lambda *args: lambda: None),
        async_add_executor_job=async_add_executor_job,
        recorder=recorder,
    )


class MeterTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_meter_does_not_expose_stale_phase_context(self):
        hass = _hass("sensor.phase_l1", "sensor.phase_l2", "sensor.phase_l3")
        manager = meter.MeterManager(hass)
        manager.mapping = {field: None for field in meter.METER_FIELDS}
        manager.mapping[meter.METER_INVERT_FIELD] = False
        manager._phase_current_entities = {"l1": "sensor.phase_l1"}
        manager._phase_source_entities = {"current": {"l1": "sensor.phase_l1"}, "voltage": {}, "active_power": {}}

        state = await manager.async_state()

        self.assertFalse(state["configured"])
        self.assertFalse(state["phase_current_available"])
        self.assertEqual(state["phase_current_entities"], {})
        self.assertEqual(state["phase_source_entities"], {"current": {}, "voltage": {}, "active_power": {}})
        self.assertEqual(manager._phase_current_entities, {})

    def test_phase_current_discovery_uses_current_unit_and_phase_metadata(self):
        class Entry:
            def __init__(self, device_id, unique_id):
                self.device_id = device_id
                self.unique_id = unique_id
                self.original_name = None

        phase_states = [
            types.SimpleNamespace(entity_id="sensor.current_l1", state="7.2", attributes={"device_class": "current", "unit_of_measurement": "A"}),
            types.SimpleNamespace(entity_id="sensor.current_l2", state="9.8", attributes={"device_class": "current", "unit_of_measurement": "A"}),
            types.SimpleNamespace(entity_id="sensor.current_l3", state="8.4", attributes={"device_class": "current", "unit_of_measurement": "A"}),
            types.SimpleNamespace(entity_id="sensor.total_current", state="20", attributes={"device_class": "current", "unit_of_measurement": "A"}),
            types.SimpleNamespace(entity_id="sensor.phase_l1_voltage", state="234", attributes={"device_class": "voltage", "unit_of_measurement": "V"}),
            types.SimpleNamespace(entity_id="sensor.phase_l2_voltage", state="235", attributes={"device_class": "voltage", "unit_of_measurement": "V"}),
            types.SimpleNamespace(entity_id="sensor.phase_l3_voltage", state="233", attributes={"device_class": "voltage", "unit_of_measurement": "V"}),
            types.SimpleNamespace(entity_id="sensor.phase_l1_power", state="1200", attributes={"device_class": "power", "unit_of_measurement": "W"}),
            types.SimpleNamespace(entity_id="sensor.phase_l2_power", state="800", attributes={"device_class": "power", "unit_of_measurement": "W"}),
            types.SimpleNamespace(entity_id="sensor.phase_l3_power", state="-400", attributes={"device_class": "power", "unit_of_measurement": "W"}),
        ]
        hass = _hass("sensor.power")
        states = {state.entity_id: state for state in phase_states}
        states["sensor.power"] = hass.states.get("sensor.power")
        hass.states.async_all = lambda *args: list(states.values())
        hass.states.get = states.get

        class Registry:
            def async_get(self, entity_id):
                return Entry("meter-device", entity_id)

        original_registry = meter.er.async_get
        meter.er.async_get = lambda _hass: Registry()
        try:
            manager = meter.MeterManager(hass)
            manager.mapping["power_entity"] = "sensor.power"
            self.assertEqual(
                manager._discover_phase_current_entities(),
                {
                    "l1": "sensor.current_l1",
                    "l2": "sensor.current_l2",
                    "l3": "sensor.current_l3",
                },
            )
            discovered = manager._discover_phase_entities()
            self.assertEqual(discovered["voltage"], {"l1": "sensor.phase_l1_voltage", "l2": "sensor.phase_l2_voltage", "l3": "sensor.phase_l3_voltage"})
            self.assertEqual(discovered["active_power"], {"l1": "sensor.phase_l1_power", "l2": "sensor.phase_l2_power", "l3": "sensor.phase_l3_power"})
        finally:
            meter.er.async_get = original_registry

    async def test_power_history_reuses_discovered_phase_entities(self):
        class Entry:
            def __init__(self, device_id, unique_id):
                self.device_id = device_id
                self.unique_id = unique_id
                self.original_name = None

        phase_entities = {
            "l1": "sensor.current_l1",
            "l2": "sensor.current_l2",
            "l3": "sensor.current_l3",
        }
        states = {
            "sensor.power": types.SimpleNamespace(
                entity_id="sensor.power", state="0", attributes={"unit_of_measurement": "kW", "device_class": "power"},
            ),
            **{
                entity_id: types.SimpleNamespace(
                    entity_id=entity_id, state=str(value),
                    attributes={"unit_of_measurement": "A", "device_class": "current"},
                    last_updated=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
                )
                for entity_id, value in zip(phase_entities.values(), (7.2, 9.8, 8.4))
            },
        }
        hass = _hass("sensor.power")
        hass.states.async_all = lambda *args: list(states.values())
        hass.states.get = states.get
        captured = []

        class Registry:
            def async_get(self, entity_id):
                return Entry("meter-device", entity_id)

        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        recorder.get_instance = lambda _hass: hass.recorder

        def get_history(*args, **kwargs):
            captured.append(kwargs["entity_ids"])
            return {
                "sensor.power": [types.SimpleNamespace(
                    state="1", attributes={"unit_of_measurement": "kW"},
                    last_updated=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
                )],
                "sensor.current_l1": [types.SimpleNamespace(
                    state="-14", attributes={"unit_of_measurement": "A", "device_class": "current"},
                    last_updated=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
                )],
                "sensor.current_l2": [types.SimpleNamespace(
                    state="9.8", attributes={"unit_of_measurement": "A", "device_class": "current"},
                    last_updated=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
                )],
                "sensor.current_l3": [types.SimpleNamespace(
                    state="8.4", attributes={"unit_of_measurement": "A", "device_class": "current"},
                    last_updated=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
                )],
            }

        history.get_significant_states = get_history
        recorder.history = history
        previous_registry = meter.er.async_get
        previous_modules = {
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
        meter.er.async_get = lambda _hass: Registry()
        try:
            manager = meter.MeterManager(hass)
            await manager.async_save_mapping({"power_entity": "sensor.power"})
            result = await manager.async_power_history()
        finally:
            meter.er.async_get = previous_registry
            for name, original in previous_modules.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original
        self.assertEqual(captured, [["sensor.power", "sensor.current_l1", "sensor.current_l2", "sensor.current_l3"]])
        self.assertEqual(result["daily_max_phase_current_a"], 14)
        self.assertEqual(result["phase_current_history"]["l1"]["max_a"], 14)
        self.assertEqual(result["phase_current_history"]["l1"]["max_timestamp"], "2026-08-23T10:00:00+00:00")
        self.assertEqual(result["daily_phase_max"]["l1"]["ampere"], 14)
        self.assertEqual(result["phase_current_source_entities"], phase_entities)
        self.assertEqual(result["phase_current_discovery_method"], "device_registry_and_phase_metadata")

    async def test_power_units_are_accepted(self):
        for unit in ("W", "kW"):
            hass = _hass("sensor.power")
            hass.states.get("sensor.power").attributes["unit_of_measurement"] = unit
            manager = meter.MeterManager(hass)
            state = await manager.async_save_mapping({"power_entity": "sensor.power"})
            self.assertEqual(state["power_entity"], "sensor.power")

    async def test_energy_units_are_normalized_and_accepted(self):
        for field, entity_id, output, valid_key in (
            ("energy_import_entity", "sensor.import", "energy_import_kwh", "energy_import_valid"),
            ("energy_export_entity", "sensor.export", "energy_export_kwh", "energy_export_valid"),
        ):
            for unit, value, expected in (("Wh", "1200", 1.2), ("kWh", "1.2", 1.2), ("MWh", "0.0012", 1.2)):
                hass = _hass(entity_id)
                entity = hass.states.get(entity_id)
                entity.attributes.update({"unit_of_measurement": unit, "device_class": "energy"})
                entity.state = value
                manager = meter.MeterManager(hass)
                state = await manager.async_save_mapping({field: entity_id})
                self.assertEqual(state[output], expected)
                self.assertTrue(state[valid_key])

    async def test_power_units_are_rejected_for_energy_mapping(self):
        for unit in ("W", "kW"):
            hass = _hass("sensor.import")
            entity = hass.states.get("sensor.import")
            entity.attributes.update({"unit_of_measurement": unit, "device_class": "power"})
            manager = meter.MeterManager(hass)
            with self.assertRaisesRegex(ValueError, "invalid_energy"):
                await manager.async_save_mapping({"energy_import_entity": "sensor.import"})

    async def test_old_invalid_energy_mapping_is_retained_but_marked_invalid(self):
        hass = _hass("sensor.import")
        entity = hass.states.get("sensor.import")
        entity.attributes.update({"unit_of_measurement": "kW", "device_class": "power"})
        manager = meter.MeterManager(hass)
        manager.mapping["energy_import_entity"] = "sensor.import"
        state = await manager.async_state()
        self.assertFalse(state["energy_import_valid"])
        self.assertIsNone(state["energy_import_kwh"])
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

    def test_inverted_positive_power_is_export(self):
        state = types.SimpleNamespace(
            state="2400",
            attributes={"unit_of_measurement": "W"},
            last_updated=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )
        point = meter.normalize_power_state(state, True)
        self.assertEqual(point["import_kw"], 0)
        self.assertEqual(point["export_kw"], 2.4)

    def test_inverted_negative_power_is_import(self):
        state = types.SimpleNamespace(
            state="-1.2",
            attributes={"unit_of_measurement": "kW"},
            last_updated=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
        )
        point = meter.normalize_power_state(state, True)
        self.assertEqual(point["import_kw"], 1.2)
        self.assertEqual(point["export_kw"], 0)

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
        recorder.get_instance = lambda hass: hass.recorder
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
        self.assertTrue(result["success"])
        self.assertEqual(result["entity_id"], "sensor.power")
        self.assertEqual(result["history"]["point_count"], 2)
        self.assertEqual(result["history"]["max_abs_kw"], 1.5)

    async def test_billing_history_reads_from_local_month_start_to_now(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        captured = []
        recorder.get_instance = lambda hass: hass.recorder
        history.get_significant_states = lambda *args, **kwargs: (
            captured.append((args[1], args[2], kwargs["entity_ids"]))
            or {
                "sensor.power": [
                    types.SimpleNamespace(
                        state="2",
                        attributes={"unit_of_measurement": "kW"},
                        last_updated=datetime(2026, 8, 1, tzinfo=timezone.utc),
                    ),
                    types.SimpleNamespace(
                        state="3",
                        attributes={"unit_of_measurement": "kW"},
                        last_updated=datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
                    ),
                ]
            }
        )
        recorder.history = history
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        previous = {
            name: sys.modules.get(name)
            for name in ("homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history")
        }
        sys.modules.update({
            "homeassistant.components": components,
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.history": history,
        })
        try:
            hass = _hass("sensor.power")
            manager = meter.MeterManager(hass)
            await manager.async_save_mapping({"power_entity": "sensor.power"})
            result = await manager.async_billing_history()
        finally:
            for name, original in previous.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original
        self.assertTrue(result["success"])
        self.assertEqual(captured, [(datetime(2026, 8, 1, tzinfo=timezone.utc), datetime(2026, 8, 23, 12, tzinfo=timezone.utc), ["sensor.power"])])
        self.assertEqual(len(result["points"]), 2)
        self.assertEqual(result["coverage"]["point_count"], 2)

    async def test_recorder_instance_executor_is_used(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        recorder.get_instance = lambda hass: hass.recorder
        history.get_significant_states = lambda *args, **kwargs: {"sensor.power": []}
        recorder.history = history
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        previous = {
            name: sys.modules.get(name)
            for name in ("homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history")
        }
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
        self.assertTrue(result["success"])
        self.assertEqual(result["points"], [])
        self.assertEqual(result["history"]["point_count"], 0)

    async def test_concurrent_history_requests_share_one_recorder_query(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        recorder.get_instance = lambda hass: hass.recorder
        history.get_significant_states = lambda *args, **kwargs: {
            "sensor.power": [
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
            calls = 0
            started = asyncio.Event()
            release = asyncio.Event()

            async def async_add_executor_job(function, *args, **kwargs):
                nonlocal calls
                calls += 1
                started.set()
                await release.wait()
                return function(*args, **kwargs)

            hass = _hass("sensor.power")
            hass.recorder.async_add_executor_job = async_add_executor_job
            diagnostics = []

            async def diagnostic(level, component, event, message):
                diagnostics.append(event)

            manager = meter.MeterManager(hass, diagnostic)
            await manager.async_save_mapping({"power_entity": "sensor.power"})
            first = asyncio.create_task(manager.async_power_history())
            await started.wait()
            second = asyncio.create_task(manager.async_power_history())
            third = asyncio.create_task(manager.async_power_history())
            await asyncio.sleep(0)
            self.assertEqual(calls, 1)
            changed = await manager.async_power_history("sensor.other")
            self.assertEqual(changed["error"], "meter_mapping_changed")
            release.set()
            results = await asyncio.gather(first, second, third)
            self.assertTrue(all(result["success"] for result in results))
            self.assertEqual(calls, 1)
            self.assertEqual(diagnostics.count("meter_history_request_success"), 0)
            await asyncio.sleep(0)
            later = await manager.async_power_history()
            self.assertTrue(later["success"])
            self.assertEqual(calls, 2)
            self.assertEqual(diagnostics.count("meter_history_request_success"), 0)
        finally:
            for name, original in previous.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

    async def test_history_failure_clears_single_flight(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        recorder.get_instance = lambda hass: hass.recorder
        calls = 0

        def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise RuntimeError("recorder unavailable")

        history.get_significant_states = fail
        recorder.history = history
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        previous = {
            name: sys.modules.get(name)
            for name in ("homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history")
        }
        sys.modules.update({
            "homeassistant.components": components,
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.history": history,
        })
        try:
            hass = _hass("sensor.power")
            manager = meter.MeterManager(hass)
            await manager.async_save_mapping({"power_entity": "sensor.power"})
            first = await manager.async_power_history()
            await asyncio.sleep(0)
            second = await manager.async_power_history()
        finally:
            for name, original in previous.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original
        self.assertFalse(first["success"])
        self.assertFalse(second["success"])
        self.assertEqual(calls, 2)

    async def test_recorder_failure_is_not_empty_success(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        recorder.get_instance = lambda hass: hass.recorder
        def fail(*args, **kwargs):
            raise RuntimeError("recorder unavailable")
        history.get_significant_states = fail
        recorder.history = history
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        previous = {
            name: sys.modules.get(name)
            for name in ("homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history")
        }
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
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "history_unavailable")

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
        self.assertTrue(all(value is None for field, value in manager.mapping.items() if field != "invert_power"))
        self.assertFalse(manager.mapping["invert_power"])

    async def test_old_store_without_invert_power_defaults_to_false(self):
        hass = _hass("sensor.power")
        manager = meter.MeterManager(hass)
        await manager.store.async_save({"power_entity": "sensor.power"})
        await manager.async_load()
        self.assertFalse(manager.mapping["invert_power"])
        self.assertFalse((await manager.async_state())["invert_power"])

    async def test_invert_power_is_saved_and_exposed_in_state_and_source(self):
        hass = _hass("sensor.power")
        manager = meter.MeterManager(hass)
        state = await manager.async_save_mapping({"power_entity": "sensor.power", "invert_power": True})
        self.assertTrue(state["invert_power"])
        self.assertTrue((await manager.async_source())["mapping"]["invert_power"])
        self.assertTrue(manager.store.data["invert_power"])

    async def test_inverted_power_is_used_for_current_state(self):
        hass = _hass("sensor.power")
        hass.states.get("sensor.power").state = "-500"
        manager = meter.MeterManager(hass)
        await manager.async_save_mapping({"power_entity": "sensor.power", "invert_power": True})
        self.assertEqual((await manager.async_state())["power_kw"], 0.5)

    async def test_invert_power_changes_history_direction(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        recorder.get_instance = lambda hass: hass.recorder
        history.get_significant_states = lambda *args, **kwargs: {
            "sensor.power": [types.SimpleNamespace(
                state="-500",
                attributes={"unit_of_measurement": "W"},
                last_updated=datetime(2026, 8, 23, 11, tzinfo=timezone.utc),
            )]
        }
        recorder.history = history
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        previous = {name: sys.modules.get(name) for name in (
            "homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history"
        )}
        sys.modules.update({
            "homeassistant.components": components,
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.history": history,
        })
        try:
            hass = _hass("sensor.power")
            manager = meter.MeterManager(hass)
            await manager.async_save_mapping({"power_entity": "sensor.power", "invert_power": True})
            result = await manager.async_power_history()
        finally:
            for name, original in previous.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original
        self.assertEqual(result["points"][0]["import_kw"], 0.5)
        self.assertEqual(result["points"][0]["export_kw"], 0)

    async def test_invert_power_is_part_of_history_single_flight_identity(self):
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        recorder.get_instance = lambda hass: hass.recorder
        history.get_significant_states = lambda *args, **kwargs: {"sensor.power": []}
        recorder.history = history
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        previous = {name: sys.modules.get(name) for name in (
            "homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history"
        )}
        sys.modules.update({
            "homeassistant.components": components,
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.history": history,
        })
        try:
            calls = 0
            started = asyncio.Event()
            release = asyncio.Event()

            async def async_add_executor_job(function, *args, **kwargs):
                nonlocal calls
                calls += 1
                started.set()
                await release.wait()
                return function(*args, **kwargs)

            hass = _hass("sensor.power")
            hass.recorder.async_add_executor_job = async_add_executor_job
            manager = meter.MeterManager(hass)
            await manager.async_save_mapping({"power_entity": "sensor.power", "invert_power": False})
            first = asyncio.create_task(manager.async_power_history())
            await started.wait()
            manager.mapping["invert_power"] = True
            second = asyncio.create_task(manager.async_power_history())
            for _ in range(3):
                await asyncio.sleep(0)
            self.assertEqual(calls, 2)
            release.set()
            await asyncio.gather(first, second)
        finally:
            for name, original in previous.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

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
