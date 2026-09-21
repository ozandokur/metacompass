"""Scanning the whole git history, not only the working tree, before a push (V7)."""

import subprocess
from pathlib import Path

import pytest

import scan_history

FAKE_KEY = "AIza" + "B" * 35  # the shape of a Google API key, not a real one
TERM = "zebracorp"


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


@pytest.fixture
def repo(tmp_path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "config.py").write_text(f'KEY = "{FAKE_KEY}"\n', encoding="utf-8")
    (tmp_path / "notes.md").write_text(
        f"Built like the {TERM.upper()} pipeline.\n", encoding="utf-8"
    )
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "first")
    # Both are removed later: the working tree is clean, the history is not.
    (tmp_path / "config.py").write_text("KEY = None\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("Built from scratch.\n", encoding="utf-8")
    git(tmp_path, "commit", "-qam", "clean up")
    return tmp_path


def test_a_secret_and_a_term_removed_later_are_still_found_in_history(repo):
    hits = scan_history.scan(repo, terms=[TERM], exact_secrets=[])
    kinds = {hit.kind for hit in hits}
    assert "Google API key" in kinds
    assert "forbidden term #1" in kinds
    assert {hit.path for hit in hits} == {"config.py", "notes.md"}


def test_the_configured_key_itself_is_looked_for(repo):
    hits = scan_history.scan(repo, terms=[], exact_secrets=[FAKE_KEY])
    assert any(hit.kind == "the configured API key" for hit in hits)


def test_commit_messages_are_scanned(repo):
    git(repo, "commit", "--allow-empty", "-qm", f"port the {TERM} loader")
    hits = scan_history.scan(repo, terms=[TERM], exact_secrets=[])
    assert any(hit.path == "(commit message)" for hit in hits)


def test_output_never_repeats_the_secret_or_the_term(repo, capsys):
    hits = scan_history.scan(repo, terms=[TERM], exact_secrets=[FAKE_KEY])
    scan_history.print_hits(hits)
    out = capsys.readouterr().out
    assert FAKE_KEY not in out and TERM not in out.lower()


def test_a_clean_history_has_no_hits(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("print('hello')\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "hello")
    assert scan_history.scan(tmp_path, terms=[TERM], exact_secrets=[FAKE_KEY]) == []
