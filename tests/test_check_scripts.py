"""Tests for the quality gate helpers: forbidden-term scan and secret scan (spec §12.3, §13.4).

The forbidden terms used here are made up for the test. Real terms live only in
docs/plan/forbidden_terms.txt, which is never committed.
"""

import subprocess
from pathlib import Path

import check_all
import check_forbidden_terms as cft


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


# ---------------------------------------------------------------- forbidden terms


def test_load_terms_skips_blank_lines_and_comments(tmp_path):
    terms_file = tmp_path / "terms.txt"
    terms_file.write_text("# comment\n\n  ZebraCorp  \nquokka-system\n", encoding="utf-8")
    assert cft.load_terms(terms_file) == ["zebracorp", "quokka-system"]


def test_term_hits_are_case_insensitive_and_report_line_numbers(tmp_path):
    (tmp_path / "notes.md").write_text("first line\nbuilt at ZEBRACORP\n", encoding="utf-8")
    hits = cft.find_term_hits([Path("notes.md")], tmp_path, ["zebracorp"])
    assert hits == [cft.TermHit(path="notes.md", line=2, term_index=1)]


def test_term_in_file_path_is_reported(tmp_path):
    (tmp_path / "zebracorp_export.csv").write_text("a,b\n", encoding="utf-8")
    hits = cft.find_term_hits([Path("zebracorp_export.csv")], tmp_path, ["zebracorp"])
    assert hits == [cft.TermHit(path="zebracorp_export.csv", line=0, term_index=1)]


def test_binary_files_are_skipped(tmp_path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00\x00zebracorp")
    assert cft.find_term_hits([Path("image.png")], tmp_path, ["zebracorp"]) == []


def test_main_returns_zero_with_warning_when_terms_file_missing(tmp_path, capsys):
    repo = _git_repo(tmp_path)
    code = cft.main(["--root", str(repo), "--terms", str(repo / "nope.txt")])
    assert code == 0
    assert "warning" in capsys.readouterr().out.lower()


def test_main_catches_term_in_untracked_but_not_ignored_file(tmp_path, capsys):
    repo = _git_repo(tmp_path)
    terms = repo / "private_terms.txt"
    terms.write_text("zebracorp\n", encoding="utf-8")
    (repo / ".gitignore").write_text("private_terms.txt\n", encoding="utf-8")
    (repo / "report.py").write_text("OWNER = 'ZebraCorp analytics'\n", encoding="utf-8")

    code = cft.main(["--root", str(repo), "--terms", str(terms)])

    out = capsys.readouterr().out
    assert code == 1
    assert "report.py:1" in out
    # The term itself is never echoed, so logs cannot leak it.
    assert "zebracorp" not in out.lower()


def test_main_ignores_gitignored_files(tmp_path):
    repo = _git_repo(tmp_path)
    terms = repo / "private_terms.txt"
    terms.write_text("zebracorp\n", encoding="utf-8")
    (repo / ".gitignore").write_text("private_terms.txt\nscratch/\n", encoding="utf-8")
    (repo / "scratch").mkdir()
    (repo / "scratch" / "tmp.txt").write_text("zebracorp\n", encoding="utf-8")
    (repo / "clean.py").write_text("x = 1\n", encoding="utf-8")

    assert cft.main(["--root", str(repo), "--terms", str(terms)]) == 0


# ---------------------------------------------------------------- secret scan

# Fake credentials are assembled at runtime so this file never matches the scanner.
FAKE_OPENAI_STYLE = "sk-" + "Ab3dE5gH7jK9mN1pQ3sT5vW7"
FAKE_ANTHROPIC_STYLE = "sk-" + "ant-" + "api03-" + "x" * 30
FAKE_HF_TOKEN = "hf_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
FAKE_KEY_ASSIGNMENT = "SERVICE_API" + "_KEY=" + "QmFzZTY0TG9va2luZ1NlY3JldFZhbHVlMTIzNDU2"


def _write(root: Path, name: str, text: str) -> Path:
    (root / name).write_text(text, encoding="utf-8")
    return Path(name)


def test_secret_scan_catches_common_key_shapes(tmp_path):
    files = [
        _write(tmp_path, "a.py", f"key = '{FAKE_OPENAI_STYLE}'\n"),
        _write(tmp_path, "b.py", f"key = '{FAKE_ANTHROPIC_STYLE}'\n"),
        _write(tmp_path, "c.txt", f"token {FAKE_HF_TOKEN}\n"),
        _write(tmp_path, "d.env", f"{FAKE_KEY_ASSIGNMENT}\n"),
    ]
    hits = check_all.find_secrets(files, tmp_path)
    assert sorted({h.path for h in hits}) == ["a.py", "b.py", "c.txt", "d.env"]


def test_secret_scan_ignores_ordinary_words(tmp_path):
    files = [
        _write(tmp_path, "prose.md", "A risk-free, disk-based task-list approach.\n"),
        _write(tmp_path, "code.py", "LLM_API_KEY = os.environ.get('LLM_API_KEY')\n"),
    ]
    assert check_all.find_secrets(files, tmp_path) == []


def test_env_example_must_leave_secret_values_empty(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(
        "LLM_API_KEY=abc\nEMBEDDING_MODEL=sentence-transformers/x\nDEMO_DAILY_LIMIT=100\n",
        encoding="utf-8",
    )
    assert check_all.check_env_example(example) == ["LLM_API_KEY"]


def test_real_env_example_is_clean():
    root = Path(__file__).resolve().parents[1]
    assert check_all.check_env_example(root / ".env.example") == []


def test_outside_a_git_checkout_the_file_listing_says_so(tmp_path):
    # V2 found it: from a ZIP download (no .git) the scans crashed with a git traceback.
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    try:
        cft.list_repo_files(tmp_path)
    except cft.NotAGitCheckout as error:
        assert "git" in str(error)
    else:
        raise AssertionError("expected NotAGitCheckout")


def test_the_secret_scan_fails_cleanly_outside_a_git_checkout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_all, "ROOT", tmp_path)
    assert check_all.run_secret_scan() is False
    assert "not a git checkout" in capsys.readouterr().out
