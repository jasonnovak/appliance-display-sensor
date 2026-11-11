from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta

from appliance_display_sensor.models import ApplianceState, DecodedDisplay


def interpreted_text(display: DecodedDisplay, *, countdown_format: str = "auto") -> str | None:
    """Interpret fixed digit positions while retaining the raw optical colon separately."""
    if countdown_format == "auto":
        return display.text
    if countdown_format != "H:MM":
        raise ValueError("countdown_format must be auto or H:MM")
    if not display.valid or len(display.digits) != 3 or not all(d.valid for d in display.digits):
        return None
    values = [None if d.value is None else str(d.value) for d in display.digits]
    # Suppressed leading positions are normal below an hour (or below ten
    # minutes). A gap after any visible glyph is not a complete reading.
    while values and values[0] is None:
        values.pop(0)
    if not values or any(value is None for value in values):
        return None
    text = "".join(values)
    if not text.isascii() or not text.isdigit():
        # Terminal messages such as End must not acquire a colon from glare.
        return text
    if len(text) != len(values) or int(text[-2:]) >= 60:
        return None
    return f"{text[0]}:{text[1:]}" if len(values) == 3 else text


def parse_remaining_minutes(
    display: DecodedDisplay, *, no_colon_unit: str, countdown_format: str = "auto",
) -> int | None:
    text = interpreted_text(display, countdown_format=countdown_format)
    if text is None:
        return None

    if ":" in text:
        hours_text, minutes_text = text.split(":", maxsplit=1)
        if not hours_text.isdigit() or not minutes_text.isdigit():
            return None
        hours = int(hours_text)
        minutes = int(minutes_text)
        if minutes >= 60:
            return None
        return hours * 60 + minutes

    if not text.isdigit():
        return None
    value = int(text)
    if countdown_format == "auto" and no_colon_unit == "seconds":
        return (value + 59) // 60
    return value


def state_from_display(
    display: DecodedDisplay,
    *,
    no_colon_unit: str,
    terminal_texts: Collection[str] = (),
    countdown_format: str = "auto",
    now: datetime | None = None,
) -> ApplianceState:
    observed_at = now or datetime.now(UTC)
    text = interpreted_text(display, countdown_format=countdown_format)
    is_terminal = text is not None and text.casefold() in {
        terminal.casefold() for terminal in terminal_texts
    }
    remaining = (
        0
        if is_terminal
        else parse_remaining_minutes(
            display, no_colon_unit=no_colon_unit, countdown_format=countdown_format,
        )
    )

    if remaining is None:
        status = "unknown"
        running = False
        estimated_finish = None
    elif is_terminal:
        status = "complete"
        running = False
        estimated_finish = observed_at
    else:
        # A displayed countdown is an appliance estimate, not necessarily a
        # monotonic clock. Numeric zero remains a running estimate unless it
        # is explicitly listed in terminal_texts. This prevents an early
        # completion event immediately before an appliance shows its actual
        # terminal message or performs a final sensing/cooling phase.
        status = "running"
        running = True
        estimated_finish = observed_at + timedelta(minutes=remaining)

    return ApplianceState(
        status=status,
        running=running,
        remaining_minutes=remaining,
        estimated_finish=estimated_finish,
        display_text=text,
        confidence=(
            min((digit.confidence for digit in display.digits), default=0.0)
            if countdown_format == "H:MM" else display.confidence
        ),
    )
