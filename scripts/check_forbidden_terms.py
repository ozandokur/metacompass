"""Scan repository files for forbidden terms (spec §13.4).

Terms live in docs/plan/forbidden_terms.txt, which is gitignored and never committed.
Scanned files are those git would commit: tracked plus untracked-but-not-ignored, so a
term is caught before the first commit, not after. Hits print as path:line and the
term's number in the terms file; the term itself is never echoed, so logs cannot leak it.

Usage: python scripts/check_forbidden_terms.py [--terms PATH] [--root PATH]
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TERMS_FILE = ROOT / "docs" / "plan" / "forbidden_terms.txt"


@dataclass(frozen=True)
class TermHit:
    path: str  # repo-relative, forward slashes
    line: int  # 1-based; 0 means the term is in the file path itself
    term_index: int  # 1-based position among the loaded terms


def load_terms(path: Path) -> list[str]:
    """One term per line, case-insensitive. Blank lines and '#' comments are ignored."""
    terms = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if term and not term.startswith("#"):
            terms.append(term.lower())
    return terms


class NotAGitCheckout(Exception):
    """The scans list the files git would commit, which needs a git checkout (not a ZIP)."""


def list_repo_files(root: Path) -> list[Path]:
    """Files git would commit, relative to root, sorted for stable output."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        raise NotAGitCheckout(f"{root} is not a git checkout; the scans need git") from error
    names = [n for n in result.stdout.decode("utf-8").split("\0") if n]
    # A tracked file deleted from the working tree is still listed; skip it.
    return sorted(Path(n) for n in set(names) if (root / n).is_file())


def read_text_or_none(path: Path) -> str | None:
    """Return file text, or None for binary / non-UTF-8 files, which are not scanned."""
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def find_term_hits(files: list[Path], root: Path, terms: list[str]) -> list[TermHit]:
    hits = []
    for rel in files:
        rel_str = rel.as_posix()
        for index, term in enumerate(terms, start=1):
            if term in rel_str.lower():
                hits.append(TermHit(rel_str, 0, index))
        text = read_text_or_none(root / rel)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for index, term in enumerate(terms, start=1):
                if term in lowered:
                    hits.append(TermHit(rel_str, line_no, index))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--terms", type=Path, default=DEFAULT_TERMS_FILE)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    if not args.terms.is_file():
        print(f"warning: forbidden terms file not found ({args.terms}); scan skipped")
        return 0
    terms = load_terms(args.terms)
    if not terms:
        print(f"warning: forbidden terms file is empty ({args.terms}); scan skipped")
        return 0

    try:
        files = list_repo_files(args.root)
    except NotAGitCheckout as error:
        print(f"forbidden terms: cannot run, {error}")
        return 1
    hits = find_term_hits(files, args.root, terms)
    for hit in hits:
        print(f"{hit.path}:{hit.line}: forbidden term #{hit.term_index}")
    if hits:
        print(f"forbidden terms: {len(hits)} hit(s) in {len(files)} scanned file(s)")
        return 1
    print(f"forbidden terms: clean ({len(terms)} term(s), {len(files)} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
