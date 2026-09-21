"""Scans the whole git history for secrets and forbidden terms before a push (V7).

    python scripts/scan_history.py          # exit 0 when the history is clean

The gate (check_all.py) scans the working tree; a push publishes every commit, so a key
committed once and deleted later is still published. This reads every blob reachable from
any ref, every commit message and every path, and looks for the credential shapes of
check_all.py, the forbidden terms of docs/plan/forbidden_terms.txt, and the exact API key
configured in .env. A hit names the path, the commit that holds it and the kind of hit;
it never prints the secret or the term.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from check_all import SECRET_PATTERNS
from check_forbidden_terms import DEFAULT_TERMS_FILE, load_terms

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class HistoryHit:
    path: str  # the path of the blob, "(commit message)" or "(path)"
    commit: str  # a commit that holds it (short SHA)
    kind: str


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def _blobs(root: Path) -> dict[str, tuple[str, str]]:
    """Every blob reachable from any ref: blob SHA -> (a path it had, a commit holding it)."""
    blobs: dict[str, tuple[str, str]] = {}
    for commit in _git(root, "rev-list", "--all").decode().split():
        listing = _git(root, "ls-tree", "-r", commit).decode("utf-8", "replace")
        for entry in listing.splitlines():
            meta, path = entry.split("\t", 1)
            _, kind, sha = meta.split()
            if kind == "blob" and sha not in blobs:
                blobs[sha] = (path, commit[:7])
    return blobs


def _read_blobs(root: Path, shas: list[str]) -> dict[str, bytes]:
    """All blob contents in one `git cat-file --batch` call."""
    out = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, input="\n".join(shas).encode() + b"\n",
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    contents, position = {}, 0
    for sha in shas:
        header_end = out.index(b"\n", position)
        size = int(out[position:header_end].split()[2])
        start = header_end + 1
        contents[sha] = out[start : start + size]
        position = start + size + 1  # the content is followed by a newline
    return contents


def _check(text: str, terms: list[str], exact_secrets: list[str]) -> list[str]:
    kinds = [kind for kind, pattern in SECRET_PATTERNS if pattern.search(text)]
    kinds += ["the configured API key" for secret in exact_secrets if secret and secret in text]
    lowered = text.lower()
    kinds += [f"forbidden term #{n}" for n, term in enumerate(terms, 1) if term in lowered]
    return kinds


def scan(root: Path, terms: list[str], exact_secrets: list[str]) -> list[HistoryHit]:
    hits: list[HistoryHit] = []
    blobs = _blobs(root)
    contents = _read_blobs(root, sorted(blobs))
    for sha, data in contents.items():
        path, commit = blobs[sha]
        if b"\0" in data[:8192]:
            continue  # binary
        text = data.decode("utf-8", "replace")
        hits += [HistoryHit(path, commit, kind) for kind in _check(text, terms, exact_secrets)]
    paths = {path: commit for path, commit in blobs.values()}
    for path, commit in paths.items():
        hits += [HistoryHit("(path)", commit, kind) for kind in _check(path, terms, [])]
    log = _git(root, "log", "--all", "--format=%h%x00%B%x01").decode("utf-8", "replace")
    for entry in log.split("\x01"):
        if "\0" in entry:
            commit, message = entry.strip("\n").split("\0", 1)
            hits += [
                HistoryHit("(commit message)", commit, kind)
                for kind in _check(message, terms, exact_secrets)
            ]
    return sorted(set(hits), key=lambda hit: (hit.path, hit.kind, hit.commit))


def print_hits(hits: list[HistoryHit]) -> None:
    for hit in hits:
        print(f"{hit.path} (in {hit.commit}): {hit.kind}")


def _configured_key() -> list[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from metacompass.config import load_settings

    key = load_settings().llm_api_key
    return [key.get_secret_value()] if key else []


def main() -> int:
    if not DEFAULT_TERMS_FILE.is_file():
        print(f"refused: {DEFAULT_TERMS_FILE} is missing; the term scan cannot run")
        return 2
    terms = load_terms(DEFAULT_TERMS_FILE)
    commits = len(_git(ROOT, "rev-list", "--all").split())
    hits = scan(ROOT, terms, _configured_key())
    print_hits(hits)
    print(
        f"history scan: {'clean' if not hits else 'FAILED'} ({commits} commits, "
        f"{len(terms)} terms, secret shapes and the configured key)"
    )
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
