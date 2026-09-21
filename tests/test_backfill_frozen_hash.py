"""Adding the frozen tree hash to result lines written before the runner recorded it (V0)."""

import json

import backfill_frozen_hash

HASHES = {"aaa1111": "h-freeze", "bbb2222": "h-later"}


def line(git_sha: str, **extra) -> dict:
    return {"item_id": "L1-001", "git_sha": git_sha, "model": "m", **extra}


def test_each_line_gets_the_hash_of_the_commit_it_was_written_under():
    lines = [line("aaa1111"), line("aaa1111-dirty"), line("bbb2222")]
    out = backfill_frozen_hash.backfill(lines, HASHES.__getitem__)
    assert [row["frozen_tree_hash"] for row in out] == ["h-freeze", "h-freeze", "h-later"]
    assert all(row["frozen_tree_hash_backfilled"] for row in out)  # said openly, not hidden


def test_a_line_that_already_has_a_hash_keeps_it():
    lines = [line("bbb2222", frozen_tree_hash="h-own")]
    out = backfill_frozen_hash.backfill(lines, HASHES.__getitem__)
    assert out[0]["frozen_tree_hash"] == "h-own"
    assert "frozen_tree_hash_backfilled" not in out[0]


def test_files_are_rewritten_in_place_with_lf(tmp_path):
    path = tmp_path / "test_A0_r1.jsonl"
    path.write_text(json.dumps(line("aaa1111")) + "\n", encoding="utf-8")
    counts = backfill_frozen_hash.backfill_file(path, HASHES.__getitem__)
    assert counts == {"h-freeze": 1}
    assert b"\r\n" not in path.read_bytes()
    assert json.loads(path.read_text(encoding="utf-8"))["frozen_tree_hash"] == "h-freeze"
