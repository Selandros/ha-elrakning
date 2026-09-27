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


def test_runtime_frame_points_keep_frame_identity_for_slot_provenance():
    class Result:
        def fetchall(self):
            return [(1_000_000, 2.5, "kW", "good", '{"source": "fixture"}')]

    class Connection:
        def execute(self, *_args):
            return Result()

    class Storage:
        def _connection(self):
            return Connection()

    points = replay_runtime._frame_points(Storage(), "frame-solar")
    assert points[0]["frame_id"] == "frame-solar"


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
