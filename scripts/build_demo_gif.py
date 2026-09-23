"""Builds the README's demo GIF out of the captured frames (phase 9).

    python scripts/build_demo_gif.py [--out assets/demo.gif] [--limit 5242880]

The frames come from scripts/capture_frames.py and are held for different times: the first
one is only a glance at an empty app, the answers need long enough to read, and the
abstention is held longest because it is the point most people miss. Between them a short
cross-fade keeps the eye in place, so the reader is not thrown by a hard cut.

A README GIF that nobody waits for is worthless, so the file has a budget. The settings are
tried in the order of what costs least to the story: first the full width, then a narrower
one, then fewer cross-fade steps, then a smaller palette. The setting that fits is printed
and recorded, and if none fits the build fails rather than shipping an oversized file.

Frames of different sizes are refused: resizing them quietly would hide a bad capture and
make the GIF jump.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FRAMES_DIR = ROOT / "assets" / "frames"
OUTPUT = ROOT / "assets" / "demo.gif"
SIZE_LIMIT = 5 * 1024 * 1024
# How long each frame stays on screen, in the order they are shown.
HOLD_MS = {
    "01_start": 1200,
    "02_impact": 2500,
    "03_trace": 2500,
    "04_record": 2500,
    "05_abstain": 3000,
}
TWEEN_MS = 80


@dataclass(frozen=True)
class Setting:
    """One rung of the ladder: how wide, how many cross-fade steps, how many colours."""

    width: int | None  # None keeps the captured width
    tweens: int
    colors: int

    def __str__(self) -> str:
        width = "full width" if self.width is None else f"width {self.width}"
        return f"{width}, {self.tweens} tween frames, {self.colors} colours"


# Ordered by what is given up: size first, then the smoothness of the cross-fade, then colour.
LADDER = (
    Setting(width=None, tweens=3, colors=256),
    Setting(width=1100, tweens=3, colors=256),
    Setting(width=960, tweens=3, colors=256),
    Setting(width=960, tweens=2, colors=256),
    Setting(width=960, tweens=2, colors=128),
    Setting(width=960, tweens=2, colors=64),
)


class FrameSizeMismatch(Exception):
    """The captured frames are not all the same size."""


class TooBig(Exception):
    """No setting on the ladder got under the budget."""


def frame_paths(folder: Path) -> list[Path]:
    """The frame files, in the order they are shown; a missing one is an error."""
    paths = []
    for name in HOLD_MS:
        path = folder / f"{name}.png"
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run scripts/capture_frames.py")
        paths.append(path)
    return paths


def load_frames(folder: Path) -> list[Image.Image]:
    frames = []
    for path in frame_paths(folder):
        image = Image.open(path).convert("RGB")
        image.load()
        frames.append(image)
    first = frames[0].size
    for path, frame in zip(frame_paths(folder), frames, strict=True):
        if frame.size != first:
            raise FrameSizeMismatch(
                f"{path.stem} is {frame.size[0]}x{frame.size[1]}, not "
                f"{first[0]}x{first[1]}; retake it instead of resizing"
            )
    return frames


def timeline(frames: list[Image.Image], setting: Setting) -> tuple[list[Image.Image], list[int]]:
    """Every picture the GIF shows and how long each one stays, held frames and tweens."""
    if setting.width is not None and frames[0].width != setting.width:
        height = round(frames[0].height * setting.width / frames[0].width)
        frames = [frame.resize((setting.width, height), Image.LANCZOS) for frame in frames]
    images: list[Image.Image] = []
    durations: list[int] = []
    for number, (frame, hold) in enumerate(zip(frames, HOLD_MS.values(), strict=True)):
        images.append(frame)
        durations.append(hold)
        if number + 1 == len(frames):
            break  # the loop back to the first frame is a cut, not a fade
        nxt = frames[number + 1]
        for step in range(1, setting.tweens + 1):
            images.append(Image.blend(frame, nxt, step / (setting.tweens + 1)))
            durations.append(TWEEN_MS)
    return images, durations


def palette(images: list[Image.Image], colors: int) -> Image.Image:
    """One palette for the whole GIF: per-frame palettes would make the colours flicker."""
    strip = Image.new("RGB", (images[0].width, images[0].height * len(images)))
    for number, image in enumerate(images):
        strip.paste(image, (0, image.height * number))
    return strip.quantize(colors=colors, method=Image.MEDIANCUT)


def render(frames: list[Image.Image], setting: Setting, out: Path) -> None:
    images, durations = timeline(frames, setting)
    master = palette(images, setting.colors)
    # No dithering: the frames are flat UI screenshots, and dither noise both looks wrong on
    # them and costs a lot of bytes, because it breaks up the runs the GIF encoder packs.
    paletted = [image.quantize(palette=master, dither=Image.NONE) for image in images]
    paletted[0].save(
        out,
        save_all=True,
        append_images=paletted[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )


def build(folder: Path, out: Path, limit: int = SIZE_LIMIT) -> Setting:
    """Writes the GIF with the first setting that fits, and returns that setting."""
    frames = load_frames(folder)
    tried = []
    for setting in LADDER:
        render(frames, setting, out)
        size = out.stat().st_size
        tried.append(f"{setting}: {size / 1024 / 1024:.2f} MB")
        if size <= limit:
            return setting
    out.unlink(missing_ok=True)
    raise TooBig(f"nothing fit in {limit / 1024 / 1024:.2f} MB; tried " + "; ".join(tried))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the README's demo GIF.")
    parser.add_argument("--frames", type=Path, default=FRAMES_DIR)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--limit", type=int, default=SIZE_LIMIT, help="bytes")
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        setting = build(args.frames, args.out, args.limit)
    except TooBig as too_big:
        print(f"FAIL {too_big}")
        return 1
    size = args.out.stat().st_size
    print(f"{args.out.name}: {size / 1024 / 1024:.2f} MB with {setting}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
