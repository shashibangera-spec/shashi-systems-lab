"""Small deterministic state monitor for a public market-data connection."""
from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from typing import Callable


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("health timestamps must be timezone-aware UTC")


class FeedHealthMonitor:
    """Emit state changes for CONNECTED, STALE and DISCONNECTED feed states."""

    def __init__(
        self,
        *,
        stale_after: timedelta,
        on_transition: Callable[[str, datetime, datetime | None], None],
    ) -> None:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive")
        self.stale_after = stale_after
        self.on_transition = on_transition
        self._lock = Lock()
        self._state = "DISCONNECTED"
        self._last_message_at: datetime | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def last_message_at(self) -> datetime | None:
        with self._lock:
            return self._last_message_at

    def _transition(self, new_state: str, at: datetime) -> None:
        _utc(at)
        callback = None
        previous = None
        with self._lock:
            if new_state != self._state:
                previous = self._state
                self._state = new_state
                callback = self.on_transition
        if callback is not None:
            callback(new_state, at, self._last_message_at)

    def connected(self, at: datetime) -> None:
        self._transition("CONNECTED", at)

    def message_received(self, at: datetime) -> None:
        _utc(at)
        with self._lock:
            self._last_message_at = at
        self._transition("CONNECTED", at)

    def disconnected(self, at: datetime) -> None:
        self._transition("DISCONNECTED", at)

    def check(self, at: datetime) -> str:
        _utc(at)
        with self._lock:
            state = self._state
            last = self._last_message_at
        if state == "CONNECTED" and last is not None and at - last > self.stale_after:
            self._transition("STALE", at)
        return self.state
