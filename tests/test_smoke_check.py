"""The one-command smoke check a built image runs (V5, V8)."""

import shutil

import pytest

import smoke_check
from metacompass.retrieval.embedders import HashEmbedder
from metacompass.service import build_components


@pytest.fixture
def built(writable_data_dir, tmp_path):
    """A checkout the way the image has it: data, warmed indices, the prepared answers."""
    shutil.copytree(writable_data_dir, tmp_path / "data")
    build_components(tmp_path / "data", HashEmbedder(dim=64))  # what warm_up.py does
    (tmp_path / "app").mkdir()
    shutil.copy(smoke_check.PROJECT_ROOT / "app" / "cached_answers.json", tmp_path / "app")
    return tmp_path


def test_a_ready_checkout_passes_every_check(built):
    results = smoke_check.checks(built, "hash")
    assert [name for name, ok, _ in results if not ok] == []
    assert len(results) == 4


def test_a_checkout_without_data_fails_the_first_check(built):
    shutil.rmtree(built / "data" / "raw")
    (built / "data" / "raw").mkdir()
    with pytest.raises(FileNotFoundError):
        smoke_check.checks(built, "hash")  # the record lookup cannot even build its store
