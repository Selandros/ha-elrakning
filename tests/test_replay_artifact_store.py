import asyncio

from tests._elrakning_test_bootstrap import install_elrakning_package_stub, install_homeassistant_stubs

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.replay_artifact_store import (
    MAX_ARTIFACTS_PER_SITE,
    ReplayArtifactStore,
    build_runtime_holdout_matrix,
    build_artifact,
    _fingerprint,
    normalize_artifact,
    validate_holdout_matrix,
)


SITE = "site-a"
KINDS = ["season", "site", "dst", "gap", "source_generation_change", "publication_cutoff"]


def _run(decision="2026-09-01T12:00:00+00:00", site=SITE):
    return {
        "site_id": site,
        "decision_at": decision,
        "run_fingerprint": "run-fingerprint",
        "input_identity": {"model": {"version": "m1"}, "calibration": {"version": "c1"}},
        "qualification": {"qualified": True, "contaminated": False, "incomplete": False, "reasons": []},
        "baselines": {"no_battery": {"points": [{"valid_at": decision}]}, "self_consumption_only": {"points": []}},
    }


def _artifact(decision="2026-09-01T12:00:00+00:00", site=SITE):
    return build_artifact(_run(decision, site), dataset_identity={"dataset": "d1"}, parameter_identity={"parameters": "p1"}, holdouts=[])


def test_artifact_round_trip_and_deterministic_identity():
    first = _artifact()
    second = _artifact()
    assert first == second
    assert normalize_artifact(first)["immutable"] is True
    tampered = {**first, "site_id": "site-b"}
    assert normalize_artifact(tampered) is None


def test_qualified_full_horizon_artifact_requires_exact_actual_coverage():
    artifact = _artifact()
    artifact["horizon"]["slot_count"] = 96
    artifact["qualification"]["actual_outcome_count"] = 95
    artifact["artifact_id"] = _fingerprint({key: value for key, value in artifact.items() if key != "artifact_id"})
    assert normalize_artifact(artifact) is None


def test_holdout_contract_requires_all_kinds_and_rejects_contaminated_cases():
    cases = [{"kind": kind, "run_fingerprint": f"fp-{kind}", "contaminated": False, "incomplete": False} for kind in KINDS]
    assert validate_holdout_matrix(cases)["qualified"] is True
    cases[0]["contaminated"] = True
    result = validate_holdout_matrix(cases)
    assert result["qualified"] is False
    assert "holdout_season_unqualified" in result["reasons"]


def test_runtime_holdout_matrix_reports_real_evidence_without_fixture_claims():
    descriptors = [
        {"descriptor_id": "a", "site_id": SITE, "local_month": 9, "qualified": True, "mature": True, "source_generations": ["gen-a"], "dst_transition": False, "actual_coverage": "96/96", "publication_cutoff_verified": True},
        {"descriptor_id": "b", "site_id": SITE, "local_month": 10, "qualified": True, "mature": True, "source_generations": ["gen-b"], "dst_transition": False, "actual_coverage": "96/96", "publication_cutoff_verified": True},
    ]
    result = build_runtime_holdout_matrix(descriptors)
    assert result["candidate_count"] == 2
    assert result["qualified_count"] == 2
    assert all(item["status"] != "qualified" for item in result["items"] if item["kind"] in {"site", "dst", "gap"})
    assert all("deterministic_fixture" not in str(item) for item in result["items"])


def test_gap_negative_evidence_does_not_disqualify_complete_windows():
    descriptors = [
        {"descriptor_id": "complete", "site_id": SITE, "local_month": 9, "qualified": True, "mature": True, "source_generations": ["gen-a"], "dst_transition": False, "actual_coverage": "96/96", "publication_cutoff_verified": True},
        {"descriptor_id": "gap", "site_id": SITE, "local_month": 9, "qualified": False, "mature": True, "source_generations": ["gen-a"], "dst_transition": False, "actual_coverage": "95/96", "publication_cutoff_verified": True},
    ]
    result = build_runtime_holdout_matrix(descriptors)
    assert result["qualified_count"] == 1
    assert result["items"][-1]["kind"] == "publication_cutoff"
    gap = next(item for item in result["items"] if item["kind"] == "gap")
    assert gap["status"] == "disqualified"
    assert result["qualified"] is False


def test_store_is_site_scoped_bounded_and_schema_fail_closed():
    class MemoryStore:
        def __init__(self, *_args, **_kwargs):
            self.value = None

        async def async_load(self):
            return self.value

        async def async_save(self, value):
            self.value = value

    store = ReplayArtifactStore(object())
    store.store = MemoryStore()

    async def run():
        await store.async_load()
        for index in range(MAX_ARTIFACTS_PER_SITE + 2):
            assert await store.async_append(_artifact(f"2026-09-01T12:{index:02d}:00+00:00")) is True
        assert len(store.state["sites"][SITE]) == MAX_ARTIFACTS_PER_SITE
        assert await store.async_append(_artifact("2026-09-01T12:127:00+00:00")) is False
        assert "site-b" not in store.state["sites"]

        store.store.value = {"schema": "wrong.v1", "version": 1, "sites": {}}
        restarted = ReplayArtifactStore(object())
        restarted.store = store.store
        await restarted.async_load()
        assert restarted.state["available"] is False
        assert await restarted.async_append(_artifact()) is False

        store.state["available"] = True
        await store.async_record_attempt({"accepted": False, "site_id": SITE, "reason": "no_mature_window", "evidence": {"count": 0}})
        assert store.state["last_attempt"]["reason"] == "no_mature_window"

    asyncio.run(run())


def test_internal_publish_builds_a_non_execution_artifact():
    artifact = build_artifact(
        _run(),
        dataset_identity={"dataset": "d1"},
        parameter_identity={"parameters": "p1"},
        holdouts=[{"kind": kind, "run_fingerprint": f"fp-{kind}"} for kind in KINDS],
    )
    assert artifact is not None
    assert artifact["provenance"]["hindsight_used_for_decision"] is False
    assert "execution" not in artifact


def test_benchmark_evidence_is_site_scoped_and_bounded_readback():
    class MemoryStore:
        def __init__(self, *_args, **_kwargs):
            self.value = None

        async def async_load(self):
            return self.value

        async def async_save(self, value):
            self.value = value

    store = ReplayArtifactStore(object())
    store.store = MemoryStore()

    async def run():
        evidence = {"available": True, "status": "blocked", "blocker": "no_good_frame", "horizon": {"actual_coverage": "0/96"}}
        assert await store.async_record_evidence(SITE, evidence) is True
        assert store.public_evidence(SITE)["site_id"] == SITE
        assert store.public_evidence("site-b")["blocker"] == "no_evidence"
        restarted = ReplayArtifactStore(object())
        restarted.store = store.store
        await restarted.async_load()
        assert restarted.public_evidence(SITE)["schema"] == "ella_replay_benchmark_evidence.v1"

    import asyncio
    asyncio.run(run())


def test_transient_no_load_snapshot_does_not_erase_known_site_metadata():
    store = ReplayArtifactStore(object())
    store.state["evidence"][SITE] = {
        "schema": "ella_replay_benchmark_evidence.v1",
        "site_id": SITE,
        "status": "blocked",
        "blocker": "no_good_frame",
        "load_frame": {"frame_id": "frame-1", "quality_status": "partial"},
        "resource_id": "ess-1",
        "economics": {"causal": True},
        "last_attempt": {"at": "old", "reason": "old_reason"},
    }
    incoming = {
        "site_id": SITE,
        "status": "blocked",
        "blocker": "no_load_frame",
        "load_frame": None,
        "resource_id": None,
        "economics": {"causal": False},
        "last_attempt": {"at": "new", "reason": "no_mature_causal_96_slot_window"},
        "runner": {"available": False},
    }

    async def save(_state):
        return None

    store.store.async_save = save
    asyncio.run(store.async_record_evidence(SITE, incoming))

    evidence = store.public_evidence(SITE)
    assert evidence["blocker"] == "no_good_frame"
    assert evidence["load_frame"]["frame_id"] == "frame-1"
    assert evidence["resource_id"] == "ess-1"
    assert evidence["economics"] == {"causal": True}
    assert evidence["last_attempt"]["reason"] == "no_mature_causal_96_slot_window"
