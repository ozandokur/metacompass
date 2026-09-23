"""Link checking for the README and the docs (V9): nothing points at something missing."""

import check_links


def test_local_links_are_checked_against_the_repository(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "there.md").write_text("x", encoding="utf-8")
    page = tmp_path / "README.md"
    page.write_text(
        "[there](docs/there.md) [gone](docs/gone.md) [anchor](#section) [img](assets/a.gif)",
        encoding="utf-8",
    )
    broken = check_links.check_local(page, tmp_path)
    assert broken == ["docs/gone.md", "assets/a.gif"]  # the anchor is not a file


def test_external_links_are_collected_without_duplicates(tmp_path):
    page = tmp_path / "README.md"
    page.write_text(
        "[a](https://example.invalid/one) [b](https://example.invalid/one) "
        "[c](http://example.invalid/two)",
        encoding="utf-8",
    )
    assert check_links.external(page) == [
        "http://example.invalid/two",
        "https://example.invalid/one",
    ]


def test_a_failing_external_link_is_reported(monkeypatch, tmp_path):
    page = tmp_path / "README.md"
    page.write_text("[a](https://example.invalid/one)", encoding="utf-8")
    monkeypatch.setattr(check_links, "status_of", lambda url: 404)
    assert check_links.check_external(page) == [("https://example.invalid/one", 404)]


def test_a_redirect_is_a_working_link(monkeypatch, tmp_path):
    # The hosted demo answers 303 and bounces through the host's auth page; a browser lands
    # on the app, which V8 confirmed.
    page = tmp_path / "README.md"
    page.write_text("[demo](https://metacompass.streamlit.app)", encoding="utf-8")
    monkeypatch.setattr(check_links, "status_of", lambda url: 303)
    assert check_links.check_external(page) == []
