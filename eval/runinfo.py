"""Run metadata shared by the eval scripts: which code produced a result file."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git_sha() -> str:
    """Short HEAD SHA, with "-dirty" when tracked files differ from it."""

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout

    sha = git("rev-parse", "--short", "HEAD").strip() or "unknown"
    # Only tracked changes count: untracked result files are outputs, not code.
    dirty = git("status", "--porcelain", "--untracked-files=no").strip()
    return sha + ("-dirty" if dirty else "")
