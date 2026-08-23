"""Provider-neutral task and subscription lifecycle management."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


LifecycleCallback = Callable[[int], Awaitable[Any]]
Unsubscribe = Callable[[], None]


class LifecycleManager:
    """Own refresh tasks, subscriptions, and stale-task generations."""

    def __init__(self, hass) -> None:
        self._hass = hass
        self._refresh_task = None
        self._consumption_task = None
        self._refresh_unsub: Unsubscribe | None = None
        self._consumption_unsub: Unsubscribe | None = None
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def refresh_task(self):
        return self._refresh_task

    @property
    def consumption_task(self):
        return self._consumption_task

    def set_refresh_unsubscribe(self, unsubscribe: Unsubscribe) -> None:
        self._refresh_unsub = unsubscribe

    def set_consumption_unsubscribe(self, unsubscribe: Unsubscribe) -> None:
        self._consumption_unsub = unsubscribe

    def has_refresh_unsubscribe(self) -> bool:
        return self._refresh_unsub is not None

    def has_consumption_unsubscribe(self) -> bool:
        return self._consumption_unsub is not None

    def start_refresh(self, callback: LifecycleCallback):
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = self._hass.async_create_task(
                callback(self._generation)
            )
        return self._refresh_task

    def start_consumption_refresh(self, callback: LifecycleCallback):
        if self._consumption_task is None or self._consumption_task.done():
            self._consumption_task = self._hass.async_create_task(
                callback(self._generation)
            )
        return self._consumption_task

    def is_current(self, generation: int) -> bool:
        return generation == self._generation

    def invalidate_generation(self) -> int:
        self._generation += 1
        return self._generation

    def cancel_tasks(self) -> None:
        if self._refresh_unsub:
            self._refresh_unsub()
            self._refresh_unsub = None
        if self._consumption_unsub:
            self._consumption_unsub()
            self._consumption_unsub = None
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        if self._consumption_task and not self._consumption_task.done():
            self._consumption_task.cancel()
        self._refresh_task = None
        self._consumption_task = None

    async def async_shutdown(self) -> None:
        self.cancel_tasks()
