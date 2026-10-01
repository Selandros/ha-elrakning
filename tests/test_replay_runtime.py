import asyncio

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.replay_artifact_store import ReplayArtifactStore
from custom_components.elrakning import replay_runtime


class _MemoryStore:
    def __init__(self):
        self.value = None

    async def async_load(self):
        return self.value

    async def async_save(self, value):
        self.value = value


class _Hass:
    def __init__(self, store):
        self.data = {"elrakning": {
            "canonical_collector": type("Collector", (), {"storage": object()})(),
            "ella_ess_facts_store": type("Facts", (), {"list_site": lambda _self, _site: []})(),
            "replay_artifact_store": store,
        }}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def test_internal_runner_builds_persists_and_reads_back_exact_site(monkeypatch):
    run = {
        "site_id": "site-a",
        "decision_at": "2026-09-24T20:08:31+00:00",
        "run_fingerprint": "run-a",
        "qualification": {"qualified": True, "contaminated": False, "incomplete": False, "reasons": []},
        "input_identity": {"model": {"version": "fixture"}},
        "baselines": {"no_battery": {"points": [{"valid_at": "x"}]}},
    }
    monkeypatch.setattr(replay_runtime, "_build_run", lambda *_args: (run, {"source": "fixture"}))
    holdouts = [{"kind": kind, "status": "qualified", "reason": "verified_test_window", "evidence": [{"descriptor_id": f"descriptor-{kind}", "site_id": "site-a"}]} for kind in ("season", "site", "dst", "gap", "source_generation_change", "publication_cutoff")]
    monkeypatch.setattr(replay_runtime, "_benchmark_readiness", lambda *_args: {"holdout_matrix": {"qualified": True, "items": holdouts, "candidate_count": 6, "mature_count": 6, "qualified_count": 6}})
    store = ReplayArtifactStore(object())
    store.store = _MemoryStore()

    async def exercise():
        hass = _Hass(store)
        result = await replay_runtime.async_generate_artifact(hass, "site-a")
        assert result["accepted"] is True
        assert result["readback"] is True
        assert result["site_id"] == "site-a"
        assert len(store.state["sites"]["site-a"]) == 1
        assert "site-b" not in store.state["sites"]
        assert result["holdouts"]["qualified"] is True

    asyncio.run(exercise())


def test_internal_runner_persists_qualified_artifact_when_global_holdouts_are_pending(monkeypatch):
    run = {
        "site_id": "site-a",
        "decision_at": "2026-09-24T20:08:31+00:00",
        "run_fingerprint": "run-pending-holdouts",
        "qualification": {"qualified": True, "contaminated": False, "incomplete": False, "reasons": []},
        "input_identity": {"model": {"version": "fixture"}},
        "baselines": {"no_battery": {"points": [{"valid_at": "x"}]}},
    }
    monkeypatch.setattr(replay_runtime, "_build_run", lambda *_args: (run, {"source": "fixture"}))
    holdouts = [{"kind": kind, "status": "pending", "reason": "future_evidence_required", "evidence": []} for kind in ("season", "site", "dst", "gap", "source_generation_change", "publication_cutoff")]
    monkeypatch.setattr(replay_runtime, "_benchmark_readiness", lambda *_args: {"holdout_matrix": {"qualified": False, "items": holdouts, "candidate_count": 1, "mature_count": 1, "qualified_count": 1}})
    store = ReplayArtifactStore(object())
    store.store = _MemoryStore()

    async def exercise():
        result = await replay_runtime.async_generate_artifact(_Hass(store), "site-a")
        assert result["accepted"] is True
        assert result["readback"] is True
        assert result["qualification"]["qualified"] is True
        assert result["evidence"]["status"] == "artifact_verified"
        assert result["evidence"]["promotion_eligible"] is False
        assert result["evidence"]["blocker"] is None
        assert result["evidence"]["last_attempt"]["reason"] is None
        assert len(store.state["sites"]["site-a"]) == 1

    asyncio.run(exercise())


def test_runtime_frame_points_keep_frame_identity_for_slot_provenance():
    class Result:
        def fetchall(self):
            return [
                (1_000_000, 2.5, "kW", "good", '{"source": "fixture"}'),
                (2_000_000, 3.0, "kW", "good", None),
                (3_000_000, None, "kW", "good", '{}'),
            ]

    class Connection:
        def execute(self, *_args):
            return Result()

    class Storage:
        def _connection(self):
            return Connection()

    points = replay_runtime._frame_points(Storage(), "frame-solar")
    assert points[0]["frame_id"] == "frame-solar"
    assert points[0]["value"] == 2.5
    assert len(points) == 2


def test_runtime_initial_state_ignores_observations_known_after_decision():
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Connection:
        def execute(self, query, _args):
            if "energy_observations" in query:
                return Result([(2_000_000, 1), (1_000_000, 2)])
            return Result([])

    class Storage:
        def _connection(self):
            return Connection()

    from datetime import datetime, timezone

    row = {"site_id": "site-a", "logical_role": "battery.soc", "interval_start": datetime.fromtimestamp(0, tz=timezone.utc)}
    decision = datetime.fromtimestamp(1.5, tz=timezone.utc)
    known_at = replay_runtime._observation_known_at(Storage(), row, decision)
    assert known_at == datetime.fromtimestamp(1, tz=timezone.utc)


def test_initial_soc_resolves_generation_resource_id_via_strong_identity():
    from datetime import datetime, timezone

    class Result:
        def fetchall(self):
            return [(1_500_000,)]

    class Connection:
        def execute(self, *_args):
            return Result()

    class Storage:
        def _connection(self):
            return Connection()

    decision = datetime.fromtimestamp(2, tz=timezone.utc)
    facts = [
        {"site_id": "site-a", "resource_id": "ess-resolved", "key": key, "value": value, "unit": unit}
        for key, value, unit in (
            ("capacity_kwh", 25, "kWh"),
            ("reserve_soc_fraction", 0.05, "fraction"),
            ("max_charge_kw", 10, "kW"),
            ("max_discharge_kw", 10, "kW"),
            ("planning_charge_efficiency", 0.85, "fraction"),
            ("planning_discharge_efficiency", 0.85, "fraction"),
        )
    ]
    row = {
        "site_id": "site-a", "logical_role": "battery.soc", "source_generation_id": "soc-generation",
        "interval_start": datetime.fromtimestamp(1, tz=timezone.utc), "known_at": datetime.fromtimestamp(1.8, tz=timezone.utc),
        "value": 13, "quality_status": "good", "coverage_ratio": 1.0,
        "provenance": {"entity_id": "sensor.soc", "source_identity": {
            "identity_strength": "strong", "config_entry_id": "cfg-1", "device_id": "dev-1",
        }},
    }
    ess, status = replay_runtime._ess_inputs(
        facts, [row], "site-a", decision,
        {"storage": Storage(), "shared": {"available": True, "resource_id": "ess-resolved", "config_entry_id": "cfg-1", "device_id": "dev-1"}, "active_generations": {"battery.soc": {"soc-generation"}}},
    )
    assert ess is not None
    assert status["initial_soc"] == 13.0
    assert status["initial_soc_source"] == "sensor.soc"
    assert status["initial_soc_identity_strength"] == "strong"


def test_initial_soc_rejects_weak_or_future_identity():
    from datetime import datetime, timezone

    class Storage:
        def _connection(self):
            class Connection:
                def execute(self, *_args):
                    class Result:
                        def fetchall(self):
                            return [(3_000_000,)]
                    return Result()
            return Connection()

    facts = [
        {"site_id": "site-a", "resource_id": "ess-resolved", "key": key, "value": value, "unit": unit}
        for key, value, unit in (("capacity_kwh", 25, "kWh"), ("reserve_soc_fraction", 0.05, "fraction"), ("max_charge_kw", 10, "kW"), ("max_discharge_kw", 10, "kW"), ("planning_charge_efficiency", 0.85, "fraction"), ("planning_discharge_efficiency", 0.85, "fraction"))
    ]
    row = {"site_id": "site-a", "logical_role": "battery.soc", "source_generation_id": "soc-generation", "interval_start": datetime.fromtimestamp(1, tz=timezone.utc), "known_at": datetime.fromtimestamp(3, tz=timezone.utc), "value": 13, "quality_status": "good", "coverage_ratio": 1.0, "provenance": {"source_identity": {"identity_strength": "weak", "config_entry_id": "cfg-1", "device_id": "dev-1"}}}
    ess, status = replay_runtime._ess_inputs(facts, [row], "site-a", datetime.fromtimestamp(2, tz=timezone.utc), {"storage": Storage(), "shared": {"available": True, "resource_id": "ess-resolved", "config_entry_id": "cfg-1", "device_id": "dev-1"}, "active_generations": {"battery.soc": {"soc-generation"}}})
    assert ess is None
    assert status["reason"] == "causal_initial_soc_missing"


def test_runtime_runner_rejects_future_economics_without_causal_override():
    from datetime import datetime, timezone

    decision = datetime(2026, 9, 24, 20, tzinfo=timezone.utc)
    economics = {
        "known_at": decision.isoformat(),
        "valid_from": "2026-10-01T00:00:00+00:00",
        "provider_valid_from": "2026-10-01T00:00:00+00:00",
        "provider_reference": "eon-agreement-test",
    }
    assert replay_runtime._economics_is_causal(economics, decision) is False
    economics["planning_applicability_override"] = {
        "source_type": "user_configured_planning_applicability_override",
        "known_at": "2026-09-26T15:26:30+00:00",
        "effective_from": "2026-09-26T15:26:30+00:00",
        "provider_valid_from": economics["provider_valid_from"],
        "provider_reference": economics["provider_reference"],
    }
    assert replay_runtime._economics_is_causal(economics, decision) is False
    assert replay_runtime._economics_is_causal(economics, datetime(2026, 9, 27, tzinfo=timezone.utc)) is True


def test_replay_economics_uses_causal_effective_dated_tariff_timeline():
    from datetime import datetime, timezone

    site = "site-vik"
    decision = datetime(2026, 9, 29, 13, 30, tzinfo=timezone.utc)
    class GridManager:
        tariff_timeline = [{
            "schema": "elrakning.grid_tariff_timeline.v1",
            "site_id": site,
            "provider": "eon",
            "source_generation_id": "eon-manual-september",
            "known_at": "2026-09-27T22:21:31.858330+00:00",
            "valid_from": "2026-08-31T22:00:00+00:00",
            "valid_to": "2026-09-30T22:00:00+00:00",
            "source_status": "MANUALLY_VERIFIED",
            "provenance": {"origin": "user_confirmed"},
            "grid_price": {"variable_total_ore_per_kwh_gross": 142.0},
        }]

    economics = replay_runtime._timeline_economics(GridManager(), site, decision)
    assert economics["provider_reference"] == "eon-manual-september"
    assert economics["known_at"] == "2026-09-27T22:21:31.858330+00:00"
    assert economics["valid_from"] == "2026-08-31T22:00:00+00:00"
    assert replay_runtime._economics_is_causal(economics, decision) is True


def test_replay_economics_reads_timeline_from_grid_manager_provider_facade():
    from datetime import datetime, timezone

    site = "site-vik"
    decision = datetime(2026, 9, 30, 7, 15, tzinfo=timezone.utc)
    record = {
        "schema": "elrakning.grid_tariff_timeline.v1",
        "site_id": site,
        "provider": "eon",
        "source_generation_id": "eon-manual-september",
        "known_at": "2026-09-27T22:21:31.858330+00:00",
        "valid_from": "2026-08-31T22:00:00+00:00",
        "valid_to": "2026-09-30T22:00:00+00:00",
        "source_status": "MANUALLY_VERIFIED",
        "provenance": {"origin": "user_confirmed"},
        "grid_price": {"variable_total_ore_per_kwh_gross": 142.0},
    }
    facade = type("GridFacade", (), {"provider": type("Provider", (), {"tariff_timeline": [record]})()})()
    economics = replay_runtime._timeline_economics(facade, site, decision)
    assert economics["provider_reference"] == "eon-manual-september"
    assert replay_runtime._economics_is_causal(economics, decision) is True


def test_replay_economics_does_not_use_future_tariff_for_pre_boundary_window():
    from datetime import datetime, timezone

    class GridManager:
        tariff_timeline = [{
            "schema": "elrakning.grid_tariff_timeline.v1",
            "site_id": "site-vik",
            "provider": "eon",
            "source_generation_id": "eon-future",
            "known_at": "2026-09-27T20:20:14.109315+00:00",
            "valid_from": "2026-09-30T22:00:00+00:00",
            "source_status": "FUTURE",
            "grid_price": {"variable_total_ore_per_kwh_gross": 142.0},
        }]

    assert replay_runtime._timeline_economics(
        GridManager(), "site-vik", datetime(2026, 9, 27, 20, tzinfo=timezone.utc)
    ) is None


def test_benchmark_readiness_reports_unqualified_frame_without_relaxing_replay(monkeypatch):
    from datetime import datetime, timezone

    load_row = ("frame-load", 1, 1, "load", 1, "generation-load", "site", "site-a", "load.forecast", "forecast", 0, 0, 1_000_000, 0, 0, 2_000_000, "partial", "{}", "{}", "frame.v1")
    monkeypatch.setattr(replay_runtime, "_frame_rows", lambda _storage, _site, role, _decision, global_scope=False: [load_row] if role == "load.forecast" else [])
    monkeypatch.setattr(replay_runtime, "_frame_points", lambda _storage, _frame_id: [])
    evidence = replay_runtime._benchmark_readiness(
        object(), [], "site-a", datetime.fromtimestamp(3, tz=timezone.utc), lambda _decision: None
    )
    assert evidence["blocker"] == "no_good_frame"
    assert evidence["qualified"] is False
    assert evidence["frame_quality"]["load"] == "partial"
    assert evidence["site_id"] == "site-a"
    assert evidence["frame_known_at"] is not None
    assert "economics_applicability" in evidence


def test_holdout_descriptors_annotate_causal_history_before_ess_inputs(monkeypatch):
    from datetime import datetime, timedelta, timezone

    decision = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
    now = decision + timedelta(days=2)
    load_row = ("load", 1, 1, "load", 1, "load-generation", "site", "site-a", "load.forecast", "forecast", 0, 0, int(decision.timestamp() * 1_000_000), 0, 0, 0, "good", "{}", "{}", "load.v1")
    slots = [decision + timedelta(minutes=15 * (index + 1)) for index in range(96)]
    soc_row = {"site_id": "site-a", "logical_role": "battery.soc", "interval_start": slots[0]}
    captured = {}

    class Storage:
        def read_site_energy_history(self, *_args):
            return [soc_row]

    def input_rows(_storage, _site_id, _decision_us, _solar):
        return []

    def window(_storage, _rows, expected, **_kwargs):
        return {
            "available": True,
            "points": {slot: {"value": 1.0, "frame": load_row} for slot in expected},
            "frames": [load_row],
            "frame_ids": [load_row[0]],
        }

    def observe_known_at(_storage, _row, _decision):
        return decision - timedelta(minutes=1)

    def ess_inputs(_facts, history, _site_id, _decision, _context):
        captured["known_at"] = history[0].get("known_at")
        return None, {"available": False, "reason": "causal_initial_soc_missing"}

    monkeypatch.setattr(replay_runtime, "_frame_rows", lambda *_args, **_kwargs: [load_row])
    monkeypatch.setattr(replay_runtime, "_frame_points", lambda *_args, **_kwargs: [{"valid_at": slot, "value": 1.0} for slot in slots])
    monkeypatch.setattr(replay_runtime, "_input_rows", input_rows)
    monkeypatch.setattr(replay_runtime, "_resolve_causal_input_window", window)
    monkeypatch.setattr(replay_runtime, "_observation_known_at", observe_known_at)
    monkeypatch.setattr(replay_runtime, "_ess_inputs", ess_inputs)

    descriptors = replay_runtime._runtime_holdout_descriptors(
        Storage(), [], "site-a", now, lambda _decision: {"known_at": decision.isoformat(), "valid_from": decision.isoformat()}
    )

    assert descriptors
    assert captured["known_at"] == decision - timedelta(minutes=1)


def test_causal_window_stitches_day_ahead_and_multiday_solar(monkeypatch):
    from datetime import datetime, timedelta, timezone

    decision = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
    slots = [decision + timedelta(minutes=15 * (index + 1)) for index in range(4)]

    def frame(frame_id, role, generation, known_at, quality="good", revision=1):
        return (frame_id, 1, 1, frame_id, revision, generation, "site", "site-a", role, "forecast", 0, 0, int(known_at.timestamp() * 1_000_000), 0, 0, 0, quality, "{}", "{}", "frame.v1")

    day = frame("solar-day", "solar.irradiance.day_ahead_pv_forecast", "solar-day-gen", decision - timedelta(hours=1))
    multiday = frame("solar-multiday", "solar.irradiance.forecast", "solar-multiday-gen", decision - timedelta(minutes=1), "partial")
    points = {
        "solar-day": [{"valid_at": slot, "value": 10.0, "quality_status": "good", "point": {}} for slot in slots[:2]],
        "solar-multiday": [{"valid_at": slot, "value": 20.0, "quality_status": "good", "point": {}} for slot in slots],
    }
    monkeypatch.setattr(replay_runtime, "_frame_points", lambda _storage, frame_id: points[frame_id])
    result = replay_runtime._resolve_causal_input_window(object(), [day, multiday], slots, solar=True, decision_us=int(decision.timestamp() * 1_000_000))
    assert result["available"] is True
    assert result["frame_ids"] == ["solar-day", "solar-multiday"]
    assert [result["points"][slot]["value"] for slot in slots] == [10.0, 10.0, 20.0, 20.0]


def test_causal_window_stitches_price_days_and_rejects_future_frames(monkeypatch):
    from datetime import datetime, timedelta, timezone

    decision = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
    slots = [decision + timedelta(minutes=15 * (index + 1)) for index in range(4)]

    def frame(frame_id, generation, known_at, revision=1):
        return (frame_id, 1, 1, frame_id, revision, generation, "global", None, "market.price.energy", "forecast", 0, 0, int(known_at.timestamp() * 1_000_000), 0, 0, 0, "good", "{}", "{}", "price.v1")

    first = frame("price-day-1", "price-gen-1", decision - timedelta(hours=1))
    second = frame("price-day-2", "price-gen-2", decision - timedelta(minutes=1))
    future = frame("price-future", "price-future-gen", decision + timedelta(minutes=1))
    points = {
        "price-day-1": [{"valid_at": slot, "value": 1.0, "quality_status": "good", "point": {}} for slot in slots[:2]],
        "price-day-2": [{"valid_at": slot, "value": 2.0, "quality_status": "good", "point": {}} for slot in slots[2:]],
        "price-future": [{"valid_at": slot, "value": 9.0, "quality_status": "good", "point": {}} for slot in slots],
    }
    monkeypatch.setattr(replay_runtime, "_frame_points", lambda _storage, frame_id: points[frame_id])
    result = replay_runtime._resolve_causal_input_window(object(), [first, second, future], slots, solar=False, decision_us=int(decision.timestamp() * 1_000_000))
    assert result["available"] is True
    assert [result["points"][slot]["value"] for slot in slots] == [1.0, 1.0, 2.0, 2.0]
    assert "price-future" not in result["frame_ids"]


def test_causal_window_fails_closed_on_overlap_generation_ambiguity(monkeypatch):
    from datetime import datetime, timedelta, timezone

    decision = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
    slot = decision + timedelta(minutes=15)

    def frame(frame_id, generation):
        return (frame_id, 1, 1, frame_id, 1, generation, "global", None, "market.price.energy", "forecast", 0, 0, int((decision - timedelta(minutes=1)).timestamp() * 1_000_000), 0, 0, 0, "good", "{}", "{}", "price.v1")

    rows = [frame("price-a", "generation-a"), frame("price-b", "generation-b")]
    monkeypatch.setattr(replay_runtime, "_frame_points", lambda _storage, frame_id: [{"valid_at": slot, "value": 1.0, "quality_status": "good", "point": {}}])
    result = replay_runtime._resolve_causal_input_window(object(), rows, [slot], solar=False, decision_us=int(decision.timestamp() * 1_000_000))
    assert result["available"] is False
    assert result["reason"] == "ambiguous_source_generation"


def test_causal_window_fails_closed_on_internal_gap_and_is_repeatable(monkeypatch):
    from datetime import datetime, timedelta, timezone

    decision = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
    slots = [decision + timedelta(minutes=15 * (index + 1)) for index in range(3)]
    row = ("solar", 1, 1, "solar", 1, "generation", "site", "site-a", "solar.irradiance.forecast", "forecast", 0, 0, int((decision - timedelta(minutes=1)).timestamp() * 1_000_000), 0, 0, 0, "partial", "{}", "{}", "solar.v1")
    points = [{"valid_at": slots[0], "value": 1.0, "quality_status": "good", "point": {"quality_status": "good"}}, {"valid_at": slots[2], "value": 3.0, "quality_status": "good", "point": {"quality_status": "good"}}]
    monkeypatch.setattr(replay_runtime, "_frame_points", lambda _storage, _frame_id: points)
    first = replay_runtime._resolve_causal_input_window(object(), [row], slots, solar=True, decision_us=int(decision.timestamp() * 1_000_000))
    second = replay_runtime._resolve_causal_input_window(object(), [row], slots, solar=True, decision_us=int(decision.timestamp() * 1_000_000))
    assert first == second
    assert first["available"] is False
    assert first["reason"] == "missing_causal_slot"
    assert first["missing_slots"] == [slots[1].isoformat()]
