"""The frozen tree hash (Ozan, 2026-09-21, V0): a fingerprint of everything that decides what
the test run measures, so a change in the middle of a days-long run cannot go unnoticed."""

import subprocess
from pathlib import Path

import pytest

import runinfo

CONFIG = '''"""Config."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TAU_Z = 4.25
PROMPT_VERSION = "v5"


class Settings:
    demo_daily_limit: int = 100
    embedding_model: str = "BAAI/bge-small-en-v1.5"


class AgentConfig:
    max_tool_calls: int = 8
'''


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    files = {
        "src/metacompass/config.py": CONFIG,
        "src/metacompass/agent/loop.py": "LOOP = 1\n",
        "src/metacompass/tools/search.py": "SEARCH = 1\n",
        "src/metacompass/retrieval/bm25.py": "K1 = 1.5\n",
        "src/metacompass/data/vocab/names.json": '["a"]\n',
        "src/metacompass/graph.py": "GRAPH = 1\n",
        "src/metacompass/api.py": "API = 1\n",
        "eval/configs.py": "CONFIGS = {}\n",
        "eval/scoring.py": "F1 = 0.8\n",
        "eval/test_set.json": '{"items": []}\n',
        "eval/report.py": "REPORT = 1\n",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    git(tmp_path, "init", "-q")
    git(tmp_path, "-c", "core.autocrlf=false", "add", ".")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "x")
    return tmp_path


def edit(repo: Path, name: str, old: str, new: str) -> None:
    path = repo / name
    path.write_bytes(path.read_bytes().replace(old.encode(), new.encode()))


def test_the_working_tree_and_its_commit_have_the_same_hash(repo):
    head = git(repo, "rev-parse", "--short", "HEAD")
    assert runinfo.frozen_tree_hash(repo) == runinfo.frozen_tree_hash(repo, commit=head)


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("src/metacompass/agent/loop.py", "1", "2"),
        ("src/metacompass/tools/search.py", "1", "2"),
        ("src/metacompass/retrieval/bm25.py", "1.5", "1.2"),
        ("src/metacompass/data/vocab/names.json", "a", "b"),
        ("src/metacompass/graph.py", "1", "2"),
        ("src/metacompass/config.py", "4.25", "4.5"),  # an eval constant
        ("src/metacompass/config.py", '"v5"', '"v6"'),  # the prompt version
        ("src/metacompass/config.py", "= 8", "= 9"),  # an AgentConfig default
        ("src/metacompass/config.py", "bge-small", "bge-base"),  # the embedding model
        ("eval/configs.py", "{}", "{1: 1}"),
        ("eval/scoring.py", "0.8", "0.7"),
        ("eval/test_set.json", "[]", "[1]"),
    ],
)
def test_a_change_to_anything_measured_changes_the_hash(repo, name, old, new):
    before = runinfo.frozen_tree_hash(repo)
    edit(repo, name, old, new)
    assert runinfo.frozen_tree_hash(repo) != before


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("src/metacompass/api.py", "1", "2"),  # serving code
        ("eval/report.py", "1", "2"),  # reporting code
        ("src/metacompass/config.py", "= 100", "= 50"),  # an app setting
        ("src/metacompass/config.py", '"""Config."""', '"""Config, reworded."""'),
    ],
)
def test_a_change_outside_the_measured_system_keeps_the_hash(repo, name, old, new):
    before = runinfo.frozen_tree_hash(repo)
    edit(repo, name, old, new)
    assert runinfo.frozen_tree_hash(repo) == before


def test_line_endings_do_not_change_the_hash(repo):
    before = runinfo.frozen_tree_hash(repo)
    edit(repo, "src/metacompass/agent/loop.py", "\n", "\r\n")
    assert runinfo.frozen_tree_hash(repo) == before
