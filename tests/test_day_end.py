"""The end-of-day routine runs the right checks, in an order whose steps depend on each other."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import day_end  # noqa: E402


def scripts_of(steps):
    return [Path(command[-1]).name for _, command in steps]


def test_every_step_points_at_a_script_that_exists():
    for _, command in day_end.STEPS:
        assert (ROOT / command[-1]).is_file(), command


def test_the_page_is_written_after_the_audits_it_must_not_contradict():
    names = scripts_of(day_end.STEPS)
    assert names.index("report.py") > names.index("audit_eval.py")
    assert names.index("report.py") > names.index("audit_cache_isolation.py")
    # The page prints the replayed numbers, so the replay has to have run first.
    assert names.index("report.py") > names.index("replay_tool_outputs.py")


def test_a_red_check_fails_the_day_and_says_which(monkeypatch, capsys):
    monkeypatch.setattr(day_end, "run", lambda label, command: "links" not in label)
    assert day_end.main([]) == 1
    printed = capsys.readouterr().out
    assert "FAIL  V9  links" in printed
    assert "do not push" in printed


def test_the_final_run_adds_the_check_for_a_finished_page(monkeypatch):
    seen = []
    monkeypatch.setattr(day_end, "run", lambda label, command: seen.append(label) is None)
    assert day_end.main(["--final"]) == 0
    assert any("final" in label for label in seen)
