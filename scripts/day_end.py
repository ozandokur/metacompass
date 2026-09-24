"""The end-of-day routine for a multi-day evaluation run (phase 8).

    python scripts/day_end.py            # every check, then regenerate the results page
    python scripts/day_end.py --final    # also demand a finished page and a full replay

The run spans days because the free tier allows 500 requests a day, so the repository is left
in a half-finished state every evening. These are the checks that have to pass before that
state is pushed, in the order their results depend on each other:

  V6  audit_eval            the raw lines are internally consistent and re-score the same
  V12 audit_cache_isolation each configuration paid for its own answers
  --  replay_tool_outputs   the IDs each answer's model was shown, for the error analysis
  V10 report.py             the results page, rewritten from the raw lines
  V9  check_links           every link in the README and the docs still resolves
  V7  scan_history          no secret or forbidden term anywhere in the history

It does not push and it does not commit: what to do with a red check is a decision, and the
script's job is to make sure the red one is seen.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

# (label, command). Ordered: the page is written after the audits it must not contradict,
# and after the replay whose numbers it prints.
STEPS = (
    ("V6  raw result audit", [PYTHON, "scripts/audit_eval.py"]),
    ("V12 cache isolation", [PYTHON, "scripts/audit_cache_isolation.py"]),
    ("--  replay tool outputs", [PYTHON, "scripts/replay_tool_outputs.py"]),
    ("V10 results page", [PYTHON, "eval/report.py"]),
    ("V9  links", [PYTHON, "scripts/check_links.py"]),
    ("V7  history scan", [PYTHON, "scripts/scan_history.py"]),
)


def run(label: str, command: list[str]) -> bool:
    print(f"\n=== {label} ===", flush=True)
    finished = subprocess.run(command, cwd=ROOT)
    return finished.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the end-of-day checks.")
    parser.add_argument(
        "--final", action="store_true", help="also require a finished page and a full replay"
    )
    args = parser.parse_args(argv)
    steps = list(STEPS)
    if args.final:
        # Only meaningful once every planned answer is in: it refuses "not run" cells and a
        # replay file that does not cover every answer.
        steps.append(("V10 final page check", [PYTHON, "scripts/check_report.py", "--final"]))
    failed = [label for label, command in steps if not run(label, command)]
    print("\n=== day end ===")
    for label, _ in steps:
        print(f"  {'FAIL' if label in failed else 'PASS'}  {label}")
    if failed:
        print("day end: FAILED — do not push")
        return 1
    print("day end: PASSED — commit the day's results, then push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
