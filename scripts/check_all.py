"""Single-command quality gate (spec §12.3, §12.6).

Runs, in order: ruff lint, ruff format check, pytest with coverage, the forbidden-term
scan and a secret scan. Every step runs even if an earlier one fails, so one invocation
shows the whole picture. Exit code 0 means the gate passed.

Usage:
    python scripts/check_all.py                    # default gate (no slow / live tests)
    python scripts/check_all.py --slow             # also run tests that download models
    python scripts/check_all.py --min-coverage 85  # enforce coverage (Phase 9)
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from check_forbidden_terms import NotAGitCheckout, list_repo_files, read_text_or_none

ROOT = Path(__file__).resolve().parents[1]

# Common credential shapes. Lookbehinds keep ordinary words ("risk-free") from matching.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sk- style API key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}")),
    ("Hugging Face token", re.compile(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{30,}")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{30,})")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "*_KEY assignment",
        re.compile(r"[A-Z0-9_]*_KEY\s*[=:]\s*[\"']?[A-Za-z0-9+/_\-]{30,}"),
    ),
]

# Variables in .env.example whose names look secret must be left empty (spec §12.3).
SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


@dataclass(frozen=True)
class SecretHit:
    path: str
    line: int
    kind: str


def find_secrets(files: list[Path], root: Path) -> list[SecretHit]:
    hits = []
    for rel in files:
        text = read_text_or_none(root / rel)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    hits.append(SecretHit(rel.as_posix(), line_no, kind))
    return hits


def check_env_example(path: Path) -> list[str]:
    """Return names of secret-looking variables that have a non-empty value."""
    offenders = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if value and any(marker in name.upper() for marker in SECRET_NAME_MARKERS):
            offenders.append(name)
    return offenders


def run_secret_scan() -> bool:
    try:
        files = list_repo_files(ROOT)
    except NotAGitCheckout:
        # A download without .git: say why the scan cannot run instead of a git traceback.
        print("secret scan: cannot run, not a git checkout (clone the repository instead)")
        return False
    hits = find_secrets(files, ROOT)
    for hit in hits:
        print(f"{hit.path}:{hit.line}: possible secret ({hit.kind})")
    env_offenders = check_env_example(ROOT / ".env.example")
    for name in env_offenders:
        print(f".env.example: {name} must be empty")
    ok = not hits and not env_offenders
    print(f"secret scan: {'clean' if ok else 'FAILED'} ({len(files)} file(s))")
    return ok


def build_steps(slow: bool, min_coverage: int | None) -> list[tuple[str, list[str]]]:
    py = sys.executable
    pytest_cmd = [py, "-m", "pytest", "-q", "--cov=metacompass", "--cov-report=term"]
    if slow:
        # A later -m overrides the default "not slow and not live" from pyproject addopts.
        pytest_cmd += ["-m", "not live"]
    if min_coverage is not None:
        pytest_cmd += [f"--cov-fail-under={min_coverage}"]
    return [
        ("ruff check", [py, "-m", "ruff", "check", "."]),
        ("ruff format --check", [py, "-m", "ruff", "format", "--check", "."]),
        ("pytest", pytest_cmd),
        ("forbidden terms", [py, str(ROOT / "scripts" / "check_forbidden_terms.py")]),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the full quality gate.")
    parser.add_argument("--slow", action="store_true", help="include tests marked slow")
    parser.add_argument("--min-coverage", type=int, default=None, metavar="PCT")
    args = parser.parse_args(argv)

    results: list[tuple[str, bool]] = []
    for name, cmd in build_steps(args.slow, args.min_coverage):
        print(f"\n=== {name} ===", flush=True)
        results.append((name, subprocess.run(cmd, cwd=ROOT).returncode == 0))
    print("\n=== secret scan ===", flush=True)
    results.append(("secret scan", run_secret_scan()))

    print("\n=== summary ===")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    passed = all(ok for _, ok in results)
    print("gate: PASSED" if passed else "gate: FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
