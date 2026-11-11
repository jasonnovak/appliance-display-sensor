from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Rect:
    """An integer rectangle expressed as x, y, width, and height."""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_value(cls, value: object, *, field_name: str) -> "Rect":
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError(f"{field_name} must contain [x, y, width, height]")
        try:
            rect = cls(*(int(component) for component in value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must contain four integers") from exc
        if rect.x < 0 or rect.y < 0 or rect.width <= 0 or rect.height <= 0:
            raise ValueError(f"{field_name} must use non-negative x/y and positive dimensions")
        return rect

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class DigitReading:
    value: str | None
    confidence: float
    valid: bool
    active_segments: tuple[str, ...]
    segment_scores: dict[str, float]


@dataclass(frozen=True)
class DecodedDisplay:
    digits: tuple[DigitReading, ...]
    colon_on: bool
    colon_after: int | None
    colon_confidence: float
    confidence: float
    valid: bool

    @property
    def text(self) -> str | None:
        if not self.valid:
            return None

        raw_digits = ["" if digit.value is None else str(digit.value) for digit in self.digits]
        if not any(raw_digits):
            return None

        if self.colon_on and self.colon_after is not None:
            left = "".join(raw_digits[: self.colon_after]).lstrip()
            right = "".join(raw_digits[self.colon_after :])
            missing_right_digit = any(
                value == "" for value in raw_digits[self.colon_after :]
            )
            if not left or not right or missing_right_digit:
                return None
            return f"{left}:{right}"

        return "".join(raw_digits).lstrip() or None


@dataclass(frozen=True)
class ApplianceState:
    status: str
    running: bool
    remaining_minutes: int | None
    estimated_finish: datetime | None
    display_text: str | None
    confidence: float

    def to_dict(self, *, appliance_type: str | None = None) -> dict[str, Any]:
        payload = asdict(self)
        payload["estimated_finish"] = (
            self.estimated_finish.isoformat() if self.estimated_finish is not None else None
        )
        payload["confidence"] = round(self.confidence, 4)
        if appliance_type:
            payload["appliance_type"] = appliance_type
        return payload
