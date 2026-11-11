from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from appliance_display_sensor.config import AppConfig
from appliance_display_sensor.decoders import SevenSegmentDecoder
from appliance_display_sensor.duration import state_from_display
from appliance_display_sensor.models import ApplianceState, DecodedDisplay
from appliance_display_sensor.stability import ReadingStabilizer


@dataclass(frozen=True)
class FrameResult:
    """Candidate and stabilized states produced from one source frame."""

    display: DecodedDisplay
    candidate_state: ApplianceState
    stable_state: ApplianceState | None
    stable_changed: bool


class FrameProcessor:
    """Apply decoding, semantics, and temporal stabilization to successive frames."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.decoder = SevenSegmentDecoder(config.display)
        self.stabilizer = ReadingStabilizer(
            confirmations=config.stability.confirmations,
            latch_completion_until_next_cycle=(
                config.stability.latch_completion_until_next_cycle
            ),
            unknown_grace_seconds=config.stability.unknown_grace_seconds,
        )
        self._last_stable_key: tuple[str, int | None] | None = None

    def process(self, image: np.ndarray, *, now: datetime | None = None) -> FrameResult:
        observed_at = now or datetime.now(UTC)
        display = self.decoder.decode(image)
        candidate = state_from_display(
            display,
            no_colon_unit=self.config.semantics.no_colon_unit,
            terminal_texts=self.config.semantics.terminal_texts,
            countdown_format=self.config.semantics.countdown_format,
            now=observed_at,
        )
        stable = self.stabilizer.observe(candidate, observed_at=observed_at)

        stable_changed = False
        if stable is not None:
            stable_key = (stable.status, stable.remaining_minutes)
            stable_changed = stable_key != self._last_stable_key
            if stable_changed:
                self._last_stable_key = stable_key

        return FrameResult(
            display=display,
            candidate_state=candidate,
            stable_state=stable,
            stable_changed=stable_changed,
        )
