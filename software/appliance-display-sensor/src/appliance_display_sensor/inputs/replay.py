from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from appliance_display_sensor.inputs.image_file import read_image


SUPPORTED_IMAGE_SUFFIXES = frozenset((".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"))


@dataclass(frozen=True)
class ReplayFrame:
    path: Path
    image: np.ndarray


def list_replay_images(directory: str | Path) -> tuple[Path, ...]:
    replay_directory = Path(directory)
    if not replay_directory.is_dir():
        raise ValueError(f"replay directory does not exist: {replay_directory}")
    paths = tuple(
        sorted(
            (
                path
                for path in replay_directory.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
            ),
            key=lambda path: path.name.casefold(),
        )
    )
    if not paths:
        raise ValueError(f"replay directory contains no supported images: {replay_directory}")
    return paths


def iter_replay(directory: str | Path, *, loop: bool = False) -> Iterator[ReplayFrame]:
    paths = list_replay_images(directory)
    while True:
        for path in paths:
            yield ReplayFrame(path=path, image=read_image(path))
        if not loop:
            return
