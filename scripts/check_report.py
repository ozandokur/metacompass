"""V10: the results page is generated, unchanged by hand, and finished (when it should be).

    python scripts/check_report.py [--final]

Regenerates eval/results.md into a temporary file and compares it with the committed page:
a line that differs means somebody edited the page instead of the raw results, or the page
is stale. It also checks that the pre-registered reading rules still hash to their pin.
With --final it additionally refuses a page that still says "not run" or "not answered yet",
and a replay file that does not cover every answer: a final page must compute its retrieval
ceiling from the replayed tool output for all of it, not for most of it.
"""

import argparse
import difflib
import json
import sys
import tempfile
from pathlib import Path

# The Windows console is not UTF-8 here; the report holds ≥, ± and ·.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import report  # noqa: E402

RESULTS_PAGE = ROOT / "eval" / "results.md"
UNFINISHED_MARKERS = (report.NOT_RUN, "not answered yet")
RESULTS_DIR = ROOT / "eval" / "results"


class GeneratorRefused(Exception):
    """report.py would not write a page (the audit of the raw results failed)."""


def generate(out: Path) -> int:
    return report.main(["--out", str(out)])


def differences(page: Path) -> list[str]:
    """Unified diff lines between the committed page and a freshly generated one."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "results.md"
        if generate(fresh) != 0:
            raise GeneratorRefused("report.py refused to write the page")
        return list(
            difflib.unified_diff(
                page.read_text(encoding="utf-8").splitlines(),
                fresh.read_text(encoding="utf-8").splitlines(),
                "committed",
                "generated",
                lineterm="",
                n=0,
            )
        )


def unfinished(page: Path) -> list[str]:
    text = page.read_text(encoding="utf-8")
    return [marker for marker in UNFINISHED_MARKERS if marker in text]


def replay_gap(results: Path = RESULTS_DIR, set_name: str = "test") -> tuple[int, int]:
    """Answers the replay file covers, of the answers there are."""
    import agent_report

    shown_path = results / f"shown_ids_{set_name}.json"
    shown = (
        json.loads(shown_path.read_text(encoding="utf-8"))["shown"]
        if shown_path.is_file()
        else None
    )
    return agent_report.replay_coverage(report.load_runs(results, set_name), shown)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the results page is generated.")
    parser.add_argument("--final", action="store_true", help="also require every answer to be in")
    args = parser.parse_args(argv)
    failures = 0
    if report.preregistration_digest() != report.PREREGISTERED_DIGEST:
        print("FAIL the pre-registered rules no longer hash to their pin")
        failures += 1
    try:
        diff = differences(RESULTS_PAGE)
    except GeneratorRefused as refused:
        print(f"FAIL {refused}; run scripts/audit_eval.py")
        return 1
    if diff:
        print("FAIL results.md differs from what eval/report.py writes:")
        print("\n".join(diff[:40]))
        failures += 1
    if args.final:
        for marker in unfinished(RESULTS_PAGE):
            print(f"FAIL the page still says {marker!r}")
            failures += 1
        covered, total = replay_gap()
        if covered != total:
            print(
                f"FAIL the replay file covers {covered} of {total} answers; "
                "run scripts/replay_tool_outputs.py"
            )
            failures += 1
    print("report check: " + ("PASSED" if not failures else "FAILED"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
