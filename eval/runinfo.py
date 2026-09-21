"""Run metadata shared by the eval scripts: which code produced a result file.

frozen_tree_hash fingerprints everything that decides what the test run measures (Ozan,
2026-09-21, V0): the agent, the tools, retrieval, the data generator and its vocabularies,
the lineage graph, the eval constants of config.py, the ablation configurations, the scoring
and the test set. Runs take days and other work goes on in the same repository meanwhile;
every result line carries this hash and the runner refuses to add to a file made under
another one, so the full system and its ablations cannot end up measuring different code
without anybody noticing.
"""

import ast
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# What must be the same for two answers to belong to one run. The git SHA may move between
# the days of a resumed run (it is recorded on every line); the frozen tree may not.
RUN_IDENTITY = ("model", "api_version", "prompt_version", "frozen_tree_hash")

FROZEN_DIRS = (
    "src/metacompass/agent",
    "src/metacompass/tools",
    "src/metacompass/retrieval",
    "src/metacompass/data",
)
FROZEN_FILES = (
    "src/metacompass/graph.py",
    "eval/configs.py",
    "eval/scoring.py",
    "eval/test_set.json",
)
CONFIG = "src/metacompass/config.py"
# Where the checkout lives differs from machine to machine; it is not part of what is measured.
CONFIG_PATH_CONSTANTS = {"PROJECT_ROOT", "DATA_DIR"}
# From config.py only these definitions count, besides the upper-case constants: the agent
# variants, the per-tool output cap, and the embedding model the retrieval benchmark chose.
CONFIG_DEFINITIONS = {"AgentConfig", "output_char_cap"}
CONFIG_SETTINGS_FIELDS = {"embedding_model"}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout


def git_sha() -> str:
    """Short HEAD SHA, with "-dirty" when tracked files differ from it."""
    sha = _git(ROOT, "rev-parse", "--short", "HEAD").strip() or "unknown"
    # Only tracked changes count: untracked result files are outputs, not code.
    dirty = _git(ROOT, "status", "--porcelain", "--untracked-files=no").strip()
    return sha + ("-dirty" if dirty else "")


def _is_constant(node: ast.stmt) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
    names = [t.id for t in targets if isinstance(t, ast.Name)]
    return bool(names) and all(n.isupper() and n not in CONFIG_PATH_CONSTANTS for n in names)


def config_constants(source: str) -> str:
    """The eval-relevant part of config.py, normalised: comments, docstrings, settings for
    the app and the location of the checkout do not change it."""
    parts = []
    for node in ast.parse(source).body:
        constant = isinstance(node, ast.Assign | ast.AnnAssign) and _is_constant(node)
        definition = (
            isinstance(node, ast.ClassDef | ast.FunctionDef) and node.name in CONFIG_DEFINITIONS
        )
        if constant or definition:
            parts.append(ast.unparse(node))
        elif isinstance(node, ast.ClassDef) and node.name == "Settings":
            parts += [
                ast.unparse(field)
                for field in node.body
                if isinstance(field, ast.AnnAssign)
                and isinstance(field.target, ast.Name)
                and field.target.id in CONFIG_SETTINGS_FIELDS
            ]
    return "\n".join(parts)


def _frozen_paths(root: Path, commit: str | None) -> list[str]:
    spec = [*FROZEN_DIRS, *FROZEN_FILES]
    if commit is None:
        listing = _git(root, "ls-files", "--", *spec)
    else:
        listing = _git(root, "ls-tree", "-r", "--name-only", commit, "--", *spec)
    return sorted(line for line in listing.splitlines() if line)


def _read(root: Path, path: str, commit: str | None) -> bytes:
    if commit is None:
        file = root / path
        return file.read_bytes() if file.is_file() else b""
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=root, capture_output=True, check=True
    ).stdout


def frozen_tree_hash(root: Path = ROOT, commit: str | None = None) -> str:
    """16 hex characters over the measured files, as they are on disk or at `commit`.

    Tracked files only, so caches and bytecode never count; CRLF is read as LF, so a
    Windows checkout and a Linux clone of the same commit agree.
    """
    digest = hashlib.sha256()
    for path in _frozen_paths(root, commit):
        content = _read(root, path, commit).replace(b"\r\n", b"\n")
        digest.update(path.encode() + b"\0" + hashlib.sha256(content).digest())
    config = _read(root, CONFIG, commit).replace(b"\r\n", b"\n").decode("utf-8")
    digest.update(CONFIG.encode() + b"#constants\0" + config_constants(config).encode("utf-8"))
    return digest.hexdigest()[:16]
