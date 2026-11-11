from __future__ import annotations

from collections.abc import Mapping


SEGMENT_ORDER = ("a", "b", "c", "d", "e", "f", "g")

# Seven-segment displays can represent a small, useful subset of letters. Keep
# these glyphs explicit so an installation can limit decoding to the symbols its
# appliance actually uses.
GLYPH_SEGMENTS: Mapping[str | None, frozenset[str]] = {
    None: frozenset(),
    "0": frozenset(("a", "b", "c", "d", "e", "f")),
    "1": frozenset(("b", "c")),
    "2": frozenset(("a", "b", "d", "e", "g")),
    "3": frozenset(("a", "b", "c", "d", "g")),
    "4": frozenset(("b", "c", "f", "g")),
    "5": frozenset(("a", "c", "d", "f", "g")),
    "6": frozenset(("a", "c", "d", "e", "f", "g")),
    "7": frozenset(("a", "b", "c")),
    "8": frozenset(SEGMENT_ORDER),
    "9": frozenset(("a", "b", "c", "d", "f", "g")),
    "E": frozenset(("a", "d", "e", "f", "g")),
    "n": frozenset(("c", "e", "g")),
    "d": frozenset(("b", "c", "d", "e", "g")),
}

DEFAULT_ALLOWED_GLYPHS = tuple(GLYPH_SEGMENTS)


def normalize_glyph(value: object) -> str | None:
    """Normalize a configuration or synthetic-fixture glyph value."""

    if value is None or value == "blank":
        return None
    glyph = str(value)
    if glyph not in GLYPH_SEGMENTS:
        supported = ", ".join("blank" if item is None else item for item in GLYPH_SEGMENTS)
        raise ValueError(f"unsupported seven-segment glyph {glyph!r}; supported: {supported}")
    return glyph
