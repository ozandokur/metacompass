"""Choose the LLM by measurement on the dev set, under the free tier's daily limits (D25).

The rule is pre-registered in results.md before these runs (report.PREREGISTERED):
  primary    the answers a model loses to the agent's own machinery, that is a run that ended
             in parse_failure or tool_budget, plus every question the run never delivered
  secondary  the overall dev accuracy
  bound      a model whose daily request limit cannot finish the 665-answer plan within
             MAX_PLAN_DAYS is not a candidate at all, whatever it scores
  tie        a non-Lite model is kept over a Lite one
Each candidate answered the same dev set once (eval/run_eval.py --model ...), in its own
folder and with its own quota log, because the daily quota is per project and per model.

Usage: python eval/model_choice.py [--dir eval/results/scratch/model_pick] [--planned 30]
  writes eval/results/model_choice.json, which report.py renders
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from runinfo import ROOT, git_sha

MACHINERY_STOPS = ("parse_failure", "tool_budget", "llm_error")
PLAN_ANSWERS = 665  # the run plan of eval/configs.py
MAX_PLAN_DAYS = 15  # Ozan, 2026-09-20: above this the free tier is not worth the wait
RULE = (
    "primary: answers lost to parse_failure, tool_budget or llm_error; secondary: dev "
    f"accuracy; a model that cannot finish {PLAN_ANSWERS} answers within {MAX_PLAN_DAYS} days "
    "is not a candidate; a tie keeps the non-Lite model"
)


class NotReady(Exception):
    """A candidate that could carry the plan has not answered the whole dev set yet."""


def summarize(
    model: str,
    lines: list[dict],
    *,
    planned: int,
    rpd: int | None,
    plan_answers: int = PLAN_ANSWERS,
    observed_rpd: int | None = None,
) -> dict:
    """What one candidate's dev run says about it, plus how long the plan would take."""
    stops = Counter(line["result"]["stopped_reason"] for line in lines)
    answered = len(lines)
    unanswered = max(planned - answered, 0)
    calls = sum(
        sum(step["kind"] == "llm" for step in line["result"]["steps"]) for line in lines
    ) / max(answered, 1)
    plan_calls = round(calls * plan_answers)
    # An llm_error answer is never written (run_eval), so it shows up as an unanswered question.
    losses = sum(stops[stop] for stop in MACHINERY_STOPS) + unanswered
    return {
        "model": model,
        "lite": "lite" in model,
        "answered": answered,
        "planned": planned,
        "unanswered": unanswered,
        "accuracy": sum(line["score"]["correct"] for line in lines) / max(answered, 1),
        "stop_reasons": dict(sorted(stops.items())),
        "machinery_losses": losses,
        "calls_per_answer": calls,
        "input_tokens_per_answer": sum(line["result"]["input_tokens"] for line in lines)
        / max(answered, 1),
        "rpd": rpd,
        "observed_rpd": observed_rpd,
        "plan_answers": plan_answers,
        "plan_calls": plan_calls,
        "plan_days": None if not rpd else -(-plan_calls // rpd),  # ceiling division
        "feasible": bool(rpd) and -(-plan_calls // rpd) <= MAX_PLAN_DAYS,
    }


def choose(candidates: list[dict]) -> tuple[dict, str]:
    """Apply the pre-registered rule; the reason names what decided it."""
    out = [c for c in candidates if c["feasible"]]
    dropped = [c for c in candidates if not c["feasible"]]
    if not out:
        raise NotReady("no candidate can finish the plan in time")
    waiting = [c for c in out if c.get("unanswered")]
    if waiting:
        names = ", ".join(f"{c['model']} ({c['answered']}/{c['planned']})" for c in waiting)
        raise NotReady(f"still answering: {names}")
    # Lowest losses first, then highest accuracy, then the non-Lite model.
    ranked = sorted(out, key=lambda c: (c["machinery_losses"], -c["accuracy"], c["lite"]))
    best = ranked[0]
    reason = (
        f"{best['model']} lost {best['machinery_losses']} answers to the agent's machinery "
        f"(parse_failure, tool_budget, llm_error) and scored {best['accuracy']:.2f} on the dev set"
    )
    if len(ranked) > 1:
        runner_up = ranked[1]
        reason += (
            f"; {runner_up['model']} lost {runner_up['machinery_losses']} and scored "
            f"{runner_up['accuracy']:.2f}"
        )
    for c in dropped:
        days = c["plan_days"]
        reason += (
            f". {c['model']} was not a candidate: {c['rpd']} requests a day means "
            f"{'no' if days is None else days} days for {c['plan_calls']} calls"
        )
    return best, reason + "."


def _quota(path: Path) -> tuple[int | None, int | None]:
    """(configured rpd, observed rpd) from a candidate's own quota log."""
    if not path.is_file():
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("limits", {}).get("rpd"), data.get("observed_rpd")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Choose the model from the candidates' dev runs.")
    parser.add_argument("--dir", type=Path, default=ROOT / "eval" / "results" / "scratch" / "model_pick")  # fmt: skip
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "results" / "model_choice.json")
    parser.add_argument("--planned", type=int, default=30, help="questions in the dev set")
    parser.add_argument("--rpd", action="append", default=[], help="model=limit from AI Studio")
    args = parser.parse_args(argv)
    stated = dict(pair.split("=", 1) for pair in args.rpd)
    candidates = []
    for folder in sorted(p for p in args.dir.iterdir() if p.is_dir()):
        path = folder / "dev_A0_r1.jsonl"
        if not path.is_file():
            continue
        lines = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines() if row]
        configured, observed = _quota(args.dir / f"quota_{folder.name}.json")
        # What the provider enforced beats the AI Studio page, which beats .env.
        rpd = observed or (int(stated[folder.name]) if folder.name in stated else configured)
        candidates.append(
            summarize(folder.name, lines, planned=args.planned, rpd=rpd, observed_rpd=observed)
        )
    if not candidates:
        print(f"no candidate runs under {args.dir}", file=sys.stderr)
        return 2
    chosen, reason = choose(candidates)
    result = {
        "metadata": {"git_sha": git_sha(), "set": "dev", "max_plan_days": MAX_PLAN_DAYS},
        "rule": RULE,
        "chosen": chosen["model"],
        "reason": reason,
        "candidates": candidates,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    for c in candidates:
        print(
            f"{c['model']:24} answered {c['answered']}/{c['planned']} · losses "
            f"{c['machinery_losses']} · accuracy {c['accuracy']:.2f} · {c['calls_per_answer']:.1f} "
            f"calls/answer · plan {c['plan_days']} days at rpd {c['rpd']}"
            f"{'' if c['feasible'] else ' (not a candidate)'}"
        )
    print(f"chosen: {chosen['model']} — {reason}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
