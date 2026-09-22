"""What the README promises about the demo and its assets (phase 9)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
DEMO_URL = "https://metacompass.streamlit.app"
GIF = ROOT / "assets" / "demo.gif"
GIF_LIMIT = 5 * 1024 * 1024  # spec phase 9: under 5 MB


def test_the_readme_links_the_hosted_demo_and_says_how_to_wake_it():
    assert f"[Live demo]({DEMO_URL})" in README
    assert "Yes, get this app back up!" in README


def test_the_demo_gif_is_small_and_shown_once_it_exists():
    if not GIF.exists():
        assert "assets/demo.gif" in README  # the placeholder says where it will go
        return
    assert GIF.stat().st_size <= GIF_LIMIT, f"{GIF.stat().st_size / 1e6:.1f} MB"
    assert "![demo](assets/demo.gif)" in README
