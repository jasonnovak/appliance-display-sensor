from __future__ import annotations

from datetime import UTC, datetime

from appliance_display_sensor.models import ApplianceState


class ReadingStabilizer:
    """Require repeated readings before exposing a changed appliance state."""

    def __init__(
        self,
        confirmations: int = 2,
        *,
        latch_completion_until_next_cycle: bool = True,
        unknown_grace_seconds: float = 15.0,
    ):
        if confirmations < 1:
            raise ValueError("confirmations must be at least 1")
        self.confirmations = confirmations
        self.latch_completion_until_next_cycle = latch_completion_until_next_cycle
        if unknown_grace_seconds < 0:
            raise ValueError("unknown_grace_seconds must not be negative")
        self.unknown_grace_seconds = unknown_grace_seconds
        self._pending_key: tuple[str, int | None] | None = None
        self._pending_count = 0
        self._confirmed: ApplianceState | None = None
        self._unknown_since: datetime | None = None

    @property
    def confirmed(self) -> ApplianceState | None:
        return self._confirmed

    def observe(
        self,
        state: ApplianceState,
        *,
        observed_at: datetime | None = None,
    ) -> ApplianceState | None:
        observed_at = observed_at or datetime.now(UTC)
        if (
            self.latch_completion_until_next_cycle
            and self._confirmed is not None
            and self._confirmed.status == "complete"
            and state.status == "unknown"
        ):
            self._pending_key = None
            self._pending_count = 0
            return self._confirmed

        if state.status == "unknown" and self._confirmed is not None:
            if self._unknown_since is None:
                self._unknown_since = observed_at
            elapsed = (observed_at - self._unknown_since).total_seconds()
            if elapsed < self.unknown_grace_seconds:
                self._pending_key = None
                self._pending_count = 0
                return self._confirmed
        else:
            self._unknown_since = None

        key = (state.status, state.remaining_minutes)
        if key == self._pending_key:
            self._pending_count += 1
        else:
            self._pending_key = key
            self._pending_count = 1

        if self._pending_count >= self.confirmations:
            self._confirmed = state
        return self._confirmed
