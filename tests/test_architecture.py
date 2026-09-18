"""Architecture rules from spec §3.2 and §12.2, enforced by static (AST) inspection.

These tests read source files instead of importing them, so a violation is caught
even in code paths that no other test exercises.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "metacompass"
APP = ROOT / "app"
EVAL = ROOT / "eval"
SCRIPTS = ROOT / "scripts"

# Frameworks and infrastructure that the scope lock (spec §2.2) rules out.
BANNED_TOP_LEVEL_IMPORTS = {
    "langchain",
    "langchain_core",
    "langchain_community",
    "langgraph",
    "crewai",
    "llama_index",
    "dspy",
    "faiss",
    "neo4j",
}

# eval/gold.py may only use pandas, json, the schema module and plain stdlib helpers
# (spec §3.2). networkx and every other metacompass module are off limits, so the gold
# answers cannot share a bug with the tools they are used to grade.
GOLD_ALLOWED_IMPORTS = {
    "__future__",
    "collections",
    "dataclasses",
    "json",
    "pathlib",
    "typing",
    "pandas",
    "metacompass.data.schema",
}

# The generator is the only module allowed to mention the metadata intent file, because it
# writes it. SPEC-DEVIATION: spec §12.2 bans the string in all of src/**, which would make
# writing the file impossible; readers (store, tools, agent, app) remain banned.
META_FILE_NAME = "_meta" + ".json"
META_WRITER_EXEMPTIONS = {SRC / "data" / "generate.py"}


def _python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _imported_modules(path: Path) -> list[str]:
    """Return fully qualified module names imported by a file (absolute imports only)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def _relative_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        "." * node.level + (node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]


def _violations(files: list[Path], forbidden_prefix: str) -> list[str]:
    found = []
    for path in files:
        for module in _imported_modules(path):
            if module == forbidden_prefix or module.startswith(forbidden_prefix + "."):
                found.append(f"{path.relative_to(ROOT)} imports {module}")
    return found


def test_tools_do_not_import_agent():
    files = _python_files(SRC / "tools")
    assert _violations(files, "metacompass.agent") == []


def test_retrieval_does_not_import_tools():
    files = _python_files(SRC / "retrieval")
    assert _violations(files, "metacompass.tools") == []


def test_src_uses_absolute_imports_only():
    # Relative imports would slip past the layer checks above.
    offenders = {
        str(path.relative_to(ROOT)): rel
        for path in _python_files(SRC)
        if (rel := _relative_imports(path))
    }
    assert offenders == {}


def test_gold_imports_only_allowed_modules():
    gold = EVAL / "gold.py"
    if not gold.exists():
        pytest.skip("eval/gold.py is created in Phase 2; rule activates automatically then")
    disallowed = [m for m in _imported_modules(gold) if m not in GOLD_ALLOWED_IMPORTS]
    assert disallowed == []
    assert _relative_imports(gold) == []


def test_no_banned_frameworks_anywhere():
    offenders = []
    for path in _python_files(SRC, APP, EVAL, SCRIPTS, ROOT / "tests"):
        for module in _imported_modules(path):
            if module.split(".")[0] in BANNED_TOP_LEVEL_IMPORTS:
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")
    assert offenders == []


def test_meta_file_not_referenced_by_runtime_code():
    offenders = [
        str(path.relative_to(ROOT))
        for path in _python_files(SRC, APP)
        if path not in META_WRITER_EXEMPTIONS and META_FILE_NAME in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_print_calls_in_src():
    offenders = []
    for path in _python_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_every_src_module_has_a_docstring():
    # Spec §13.1 rule 10: every module starts with a short purpose description.
    missing = []
    for path in _python_files(SRC):
        source = path.read_text(encoding="utf-8")
        if path.name == "__init__.py" and not source.strip():
            continue
        if ast.get_docstring(ast.parse(source)) is None:
            missing.append(str(path.relative_to(ROOT)))
    assert missing == []
