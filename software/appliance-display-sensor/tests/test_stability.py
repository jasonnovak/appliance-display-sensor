from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from appliance_display_sensor.models import ApplianceState
from appliance_display_sensor.stability import ReadingStabilizer


def running_state(
    minutes: int,
    *,
    observed_at: datetime | None = None,
) -> ApplianceState:
    observed_at = observed_at or datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    return ApplianceState(
        status="running",
        running=True,
        remaining_minutes=minutes,
        estimated_finish=observed_at + timedelta(minutes=minutes),
        display_text=str(minutes),
        confidence=0.98,
    )


def complete_state() -> ApplianceState:
    observed_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    return ApplianceState(
        status="complete",
        running=False,
        remaining_minutes=0,
        estimated_finish=observed_at,
        display_text="End",
        confidence=0.99,
    )


def unknown_state() -> ApplianceState:
    return ApplianceState(
        status="unknown",
        running=False,
        remaining_minutes=None,
        estimated_finish=None,
        display_text=None,
        confidence=1.0,
    )


class ReadingStabilizerTests(unittest.TestCase):
    def test_requires_repeated_candidate_before_change(self) -> None:
        stabilizer = ReadingStabilizer(confirmations=2)

        self.assertIsNone(stabilizer.observe(running_state(41)))
        self.assertEqual(stabilizer.observe(running_state(41)).remaining_minutes, 41)
        self.assertEqual(stabilizer.observe(running_state(40)).remaining_minutes, 41)
        self.assertEqual(stabilizer.observe(running_state(40)).remaining_minutes, 40)

    def test_latches_end_across_blank_until_next_cycle(self) -> None:
        stabilizer = ReadingStabilizer(
            confirmations=2,
            latch_completion_until_next_cycle=True,
        )

        self.assertIsNone(stabilizer.observe(complete_state()))
        self.assertEqual(stabilizer.observe(complete_state()).status, "complete")

        for _ in range(30):
            self.assertEqual(stabilizer.observe(unknown_state()).status, "complete")

        self.assertEqual(stabilizer.observe(running_state(41)).status, "complete")
        next_cycle = stabilizer.observe(running_state(41))
        self.assertEqual(next_cycle.status, "running")
        self.assertEqual(next_cycle.remaining_minutes, 41)

    def test_accepts_confirmed_adaptive_increase_and_decrease(self) -> None:
        stabilizer = ReadingStabilizer(confirmations=2)
        started_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

        stabilizer.observe(running_state(35, observed_at=started_at))
        initial = stabilizer.observe(running_state(35, observed_at=started_at))
        self.assertEqual(initial.remaining_minutes, 35)
        self.assertEqual(initial.estimated_finish, started_at + timedelta(minutes=35))

        extended_at = started_at + timedelta(minutes=1)
        self.assertEqual(
            stabilizer.observe(running_state(42, observed_at=extended_at)).remaining_minutes,
            35,
        )
        extended = stabilizer.observe(running_state(42, observed_at=extended_at))
        self.assertEqual(extended.remaining_minutes, 42)
        self.assertEqual(extended.estimated_finish, extended_at + timedelta(minutes=42))

        shortened_at = started_at + timedelta(minutes=2)
        self.assertEqual(
            stabilizer.observe(running_state(18, observed_at=shortened_at)).remaining_minutes,
            42,
        )
        shortened = stabilizer.observe(running_state(18, observed_at=shortened_at))
        self.assertEqual(shortened.remaining_minutes, 18)
        self.assertEqual(shortened.estimated_finish, shortened_at + timedelta(minutes=18))

    def test_keeps_running_state_during_brief_unknown_gap(self) -> None:
        stabilizer = ReadingStabilizer(
            confirmations=2,
            unknown_grace_seconds=15,
        )
        started_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        stabilizer.observe(running_state(19), observed_at=started_at)
        confirmed = stabilizer.observe(
            running_state(19),
            observed_at=started_at + timedelta(seconds=1),
        )
        self.assertEqual(confirmed.remaining_minutes, 19)

        for seconds in (2, 5, 14):
            held = stabilizer.observe(
                unknown_state(),
                observed_at=started_at + timedelta(seconds=seconds),
            )
            self.assertEqual(held.status, "running")
            self.assertEqual(held.remaining_minutes, 19)

    def test_accepts_unknown_after_grace_and_confirmations(self) -> None:
        stabilizer = ReadingStabilizer(
            confirmations=2,
            unknown_grace_seconds=10,
        )
        started_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        stabilizer.observe(running_state(19), observed_at=started_at)
        stabilizer.observe(running_state(19), observed_at=started_at + timedelta(seconds=1))

        stabilizer.observe(unknown_state(), observed_at=started_at + timedelta(seconds=2))
        still_running = stabilizer.observe(
            unknown_state(),
            observed_at=started_at + timedelta(seconds=12),
        )
        self.assertEqual(still_running.status, "running")
        accepted = stabilizer.observe(
            unknown_state(),
            observed_at=started_at + timedelta(seconds=13),
        )
        self.assertEqual(accepted.status, "unknown")

    def test_valid_reading_restarts_unknown_grace_period(self) -> None:
        stabilizer = ReadingStabilizer(
            confirmations=2,
            unknown_grace_seconds=10,
        )
        started_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        stabilizer.observe(running_state(19), observed_at=started_at)
        stabilizer.observe(running_state(19), observed_at=started_at + timedelta(seconds=1))
        stabilizer.observe(unknown_state(), observed_at=started_at + timedelta(seconds=8))
        stabilizer.observe(running_state(19), observed_at=started_at + timedelta(seconds=9))
        held = stabilizer.observe(
            unknown_state(),
            observed_at=started_at + timedelta(seconds=15),
        )
        self.assertEqual(held.status, "running")


if __name__ == "__main__":
    unittest.main()
