"""The demo GIF is built from the captured frames, in order, and stays small enough to ship."""

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_demo_gif as gif  # noqa: E402


def test_every_frame_the_gif_needs_is_on_disk():
    names = [path.stem for path in gif.frame_paths(gif.FRAMES_DIR)]
    assert names == list(gif.HOLD_MS)


def test_frames_are_read_in_order():
    frames = gif.load_frames(gif.FRAMES_DIR)
    assert len(frames) == len(gif.HOLD_MS)
    assert {frame.size for frame in frames} == {(1280, 720)}


def test_a_frame_of_another_size_is_refused(tmp_path):
    """Silently resizing would hide a bad capture and make the GIF jump."""
    for name in gif.HOLD_MS:
        Image.new("RGB", (1280, 720), "white").save(tmp_path / f"{name}.png")
    Image.new("RGB", (1280, 700), "white").save(tmp_path / "03_trace.png")
    with pytest.raises(gif.FrameSizeMismatch) as raised:
        gif.load_frames(tmp_path)
    assert "03_trace" in str(raised.value)


def test_the_timeline_holds_each_frame_for_its_own_time():
    frames = [
        Image.new("RGB", (8, 8), colour) for colour in ("red", "green", "blue", "grey", "black")
    ]
    setting = gif.Setting(width=None, tweens=3, colors=256)
    images, durations = gif.timeline(frames, setting)
    assert len(images) == len(durations)
    # Five held frames, and three cross-fade steps in each of the four gaps between them.
    assert len(images) == 5 + 4 * 3
    assert [d for d in durations if d != gif.TWEEN_MS] == list(gif.HOLD_MS.values())
    assert durations[:5] == [1200, gif.TWEEN_MS, gif.TWEEN_MS, gif.TWEEN_MS, 2500]


def test_fewer_tweens_make_a_shorter_timeline():
    frames = [Image.new("RGB", (8, 8), "white") for _ in gif.HOLD_MS]
    images, _ = gif.timeline(frames, gif.Setting(width=None, tweens=2, colors=256))
    assert len(images) == 5 + 4 * 2


def test_it_writes_a_looping_gif_under_the_size_limit(tmp_path):
    out = tmp_path / "demo.gif"
    setting = gif.build(gif.FRAMES_DIR, out, gif.SIZE_LIMIT)
    assert setting in gif.LADDER
    assert out.stat().st_size <= gif.SIZE_LIMIT
    with Image.open(out) as built:
        assert built.format == "GIF"
        assert built.info["loop"] == 0  # forever
        assert built.n_frames == 5 + 4 * setting.tweens


def test_it_says_so_when_no_setting_fits(tmp_path):
    """A GIF that misses the budget must fail loudly, not ship over the limit."""
    with pytest.raises(gif.TooBig):
        gif.build(gif.FRAMES_DIR, tmp_path / "demo.gif", limit=1024)
