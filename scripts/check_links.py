"""Checks every link in the README and the docs (V9).

    python scripts/check_links.py [--page README.md ...]

A portfolio page whose links 404 is worse than no page. Local links must point at a file in
the repository; an external one works when it answers below 400, redirects included (the
hosted demo answers 303 through its host's auth page and lands on the app). Anchors
(#section) and mailto: links are left alone. Rate-limited or blocked hosts (429, 403) are
reported, not failed: they say nothing about the link.
"""

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAGES = ("README.md", "docs/architecture.md", "docs/data_card.md")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
TOLERATED = {403, 429}  # a host refusing a robot, not a broken link
USER_AGENT = "MetaCompass link check"


def _targets(page: Path) -> list[str]:
    return LINK.findall(page.read_text(encoding="utf-8"))


def check_local(page: Path, root: Path = ROOT) -> list[str]:
    """Local link targets that do not exist, in the order they appear."""
    missing = []
    for target in _targets(page):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = (root / target.split("#")[0]).resolve()
        if not path.exists() and target.split("#")[0] not in missing:
            missing.append(target.split("#")[0])
    return missing


def external(page: Path) -> list[str]:
    return sorted({t for t in _targets(page) if t.startswith(("http://", "https://"))})


def status_of(url: str) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return 0  # no answer at all


def check_external(page: Path) -> list[tuple[str, int]]:
    """External links that did not answer below 400 (403 and 429 are reported, not failed)."""
    return [(url, status) for url in external(page) if not 200 <= (status := status_of(url)) < 400]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the links of the project's pages.")
    parser.add_argument("--page", action="append", default=[], help="repeatable")
    args = parser.parse_args(argv)
    pages = [ROOT / p for p in (args.page or DEFAULT_PAGES)]
    failures = 0
    for page in pages:
        missing = check_local(page)
        bad = check_external(page)
        for target in missing:
            print(f"{page.name}: missing file {target}")
        for url, status in bad:
            kind = "unreachable" if status in TOLERATED or status == 0 else "broken"
            print(f"{page.name}: {kind} link ({status}) {url}")
        failures += len(missing) + sum(1 for _, status in bad if status not in TOLERATED)
        print(f"{page.name}: {len(_targets(page))} links checked")
    print("links: " + ("clean" if not failures else f"{failures} FAILED"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
