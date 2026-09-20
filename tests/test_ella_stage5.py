import asyncio
import copy

from tests._elrakning_test_bootstrap import install_homeassistant_stubs, install_elrakning_package_stub

install_homeassistant_stubs()
install_elrakning_package_stub()

from custom_components.elrakning.ella_learning import EllaLearningStore


class _Store:
    def __init__(self, value=None):
        self.value = value

    async def async_load(self):
        return copy.deepcopy(self.value)

    async def async_save(self, value):
        self.value = copy.deepcopy(value)


def test_learning_store_is_site_scoped_bounded_and_restart_safe():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        for index in range(520):
            await store.async_record("site-a", {
                "records": [{"frame_id": f"frame-{index}", "revision": 1, "valid_at": f"2026-09-{index // 20 + 1:02d}T00:00:00+00:00"}],
                "summary": {"count": 1},
            }, {"factor": 1.0})
        assert len(store.state["sites"]["site-a"]["records"]) == 512
        assert store.public_state("site-b")["available"] is False
        restarted = EllaLearningStore(object())
        restarted.store = _Store(store.state)
        await restarted.async_load()
        assert len(restarted.state["sites"]["site-a"]["records"]) == 512
        assert restarted.public_state("site-a")["calibration"] == {"factor": 1.0}
    asyncio.run(run())


def test_learning_store_does_not_create_execution_failure_without_actuator():
    async def run():
        store = EllaLearningStore(object())
        store.store = _Store()
        await store.async_record("site-a", {"records": []}, {"factor": 1.0})
        result = store.public_state("site-a")
        assert result["available"] is False
    asyncio.run(run())
