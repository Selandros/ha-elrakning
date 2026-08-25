import asyncio
import sys
import types
import unittest
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_power_module():
    homeassistant = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    storage = types.ModuleType("homeassistant.helpers.storage")
    util = types.ModuleType("homeassistant.util")
    dt_module = types.ModuleType("homeassistant.util.dt")
    core.EVENT_STATE_CHANGED = "state_changed"
    core.Event = object
    core.State = object
    core.valid_entity_id = lambda value: isinstance(value, str) and value.startswith("sensor.") and len(value) > 7
    dt_module.now = lambda: datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    dt_module.start_of_local_day = lambda value: value.replace(hour=0, minute=0, second=0, microsecond=0)

    class Store:
        def __init__(self, *args):
            self.data = None

        async def async_load(self):
            return self.data

        async def async_save(self, data):
            self.data = data

    storage.Store = Store
    helpers.storage = storage
    util.dt = dt_module
    homeassistant.core = core
    homeassistant.helpers = helpers
    homeassistant.util = util
    modules = {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_module,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    package = types.ModuleType("custom_components.elrakning")
    package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "elrakning")]
    sys.modules["custom_components.elrakning"] = package
    meter_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "meter.py"
    meter_spec = spec_from_file_location("custom_components.elrakning.meter", meter_path)
    meter_module = module_from_spec(meter_spec)
    sys.modules[meter_spec.name] = meter_module
    meter_spec.loader.exec_module(meter_module)
    power_path = Path(__file__).parents[1] / "custom_components" / "elrakning" / "power.py"
    power_spec = spec_from_file_location("custom_components.elrakning.power", power_path)
    power_module = module_from_spec(power_spec)
    sys.modules[power_spec.name] = power_module
    power_spec.loader.exec_module(power_module)
    for name, original in previous.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    return power_module


power = _load_power_module()


def _state(value, unit, timestamp=None):
    return types.SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit},
        last_updated=timestamp or datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
    )


def _hass(states):
    async def async_add_executor_job(function, *args, **kwargs):
        return function(*args, **kwargs)

    return types.SimpleNamespace(
        states=types.SimpleNamespace(get=states.get),
        bus=types.SimpleNamespace(async_listen=lambda *args: lambda: None, async_fire=lambda *args: None),
        recorder=types.SimpleNamespace(async_add_executor_job=async_add_executor_job),
    )


class PowerTests(unittest.IsolatedAsyncioTestCase):
    async def test_mapping_and_current_state_cover_solar_load_and_battery(self):
        states = {
            "sensor.mppt_1": _state(1000, "W"),
            "sensor.mppt_2": _state(0.5, "kW"),
            "sensor.load": _state(1.2, "kW"),
            "sensor.charge": _state(300, "W"),
            "sensor.discharge": _state(0.2, "kW"),
            "sensor.soc": _state(73, "%"),
            "sensor.capacity": _state(10, "kWh"),
        }
        manager = power.PowerManager(_hass(states))
        result = await manager.async_save_mapping({
            "solar_entities": ["sensor.mppt_1", "sensor.mppt_2"],
            "consumption_entity": "sensor.load",
            "charging_entity": "sensor.charge",
            "discharging_entity": "sensor.discharge",
            "soc_entity": "sensor.soc",
            "capacity_entity": "sensor.capacity",
        })
        self.assertEqual(result["solar_kw"], 1.5)
        self.assertEqual(result["consumption_kw"], 1.2)
        self.assertEqual(result["charging_kw"], 0.3)
        self.assertEqual(result["discharging_kw"], 0.2)
        self.assertEqual(result["soc_percent"], 73)
        self.assertEqual(result["capacity_kwh"], 10)

    async def test_power_units_are_rejected(self):
        manager = power.PowerManager(_hass({"sensor.energy": _state(2, "kWh")}))
        with self.assertRaisesRegex(ValueError, "invalid_power_unit"):
            await manager.async_save_mapping({"solar_entities": ["sensor.energy"]})

    async def test_history_sums_mppt_timelines_without_array_index_merging(self):
        states = {"sensor.mppt_1": _state(0, "W"), "sensor.mppt_2": _state(0, "W")}
        hass = _hass(states)
        manager = power.PowerManager(hass)
        await manager.async_save_mapping({"solar_entities": ["sensor.mppt_1", "sensor.mppt_2"]})
        recorder = types.ModuleType("homeassistant.components.recorder")
        history = types.ModuleType("homeassistant.components.recorder.history")
        calls = []
        recorder.get_instance = lambda _: hass.recorder
        history.get_significant_states = lambda *args, **kwargs: (
            calls.append(1) or {
                "sensor.mppt_1": [_state(1000, "W", datetime(2026, 8, 23, 10, tzinfo=timezone.utc))],
                "sensor.mppt_2": [
                    _state(500, "W", datetime(2026, 8, 23, 10, 5, tzinfo=timezone.utc)),
                    _state(700, "W", datetime(2026, 8, 23, 11, tzinfo=timezone.utc)),
                ],
            }
        )
        recorder.history = history
        components = types.ModuleType("homeassistant.components")
        components.recorder = recorder
        previous = {name: sys.modules.get(name) for name in ("homeassistant.components", "homeassistant.components.recorder", "homeassistant.components.recorder.history")}
        sys.modules.update({"homeassistant.components": components, "homeassistant.components.recorder": recorder, "homeassistant.components.recorder.history": history})
        try:
            first, second = await asyncio.gather(manager.async_history(), manager.async_history())
        finally:
            for name, original in previous.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original
        self.assertEqual(len(calls), 1)
        points = first["series"]["solar"]["points"]
        self.assertEqual(points[0]["value_kw"], 1.0)
        self.assertEqual(points[1]["value_kw"], 1.5)
        self.assertEqual(points[2]["value_kw"], 1.7)
        self.assertEqual(second, first)

