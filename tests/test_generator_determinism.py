"""I17: the generator is byte-for-byte deterministic for a fixed seed (spec §4.1, §4.7)."""

import hashlib
from pathlib import Path

from metacompass.data.generate import generate, write_outputs


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_I17_two_runs_produce_identical_files(tmp_path, generated_dir):
    first, second = tmp_path / "first", tmp_path / "second"
    write_outputs(generate(seed=42), first)
    write_outputs(generate(seed=42), second)
    hashes = _hashes(first)
    assert len(hashes) == 8  # seven CSVs + the metadata intent file
    assert hashes == _hashes(second)
    # The session-wide dataset used by the other tests is the same bytes too.
    assert hashes == _hashes(generated_dir)


def test_I17_files_use_unix_line_endings(generated_dir):
    for path in (generated_dir / "raw").glob("*.csv"):
        assert b"\r\n" not in path.read_bytes(), path.name


def test_different_seed_changes_the_data(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_outputs(generate(seed=42), a)
    write_outputs(generate(seed=7), b)
    assert _hashes(a) != _hashes(b)
