"""The image build step that makes a fresh checkout ready to answer (spec §11.1)."""

import warm_up


def test_a_fresh_folder_gets_the_data_and_the_dense_index_cache(tmp_path):
    data = tmp_path / "data"
    assert warm_up.main(["--data", str(data), "--embedder", "hash"]) == 0
    assert (data / "raw" / "reports.csv").is_file()  # generated with seed 42
    cached = list((data / "cache").rglob("*"))
    assert any(path.is_file() for path in cached)  # document embeddings, computed once


def test_existing_data_is_not_regenerated(tmp_path):
    data = tmp_path / "data"
    warm_up.main(["--data", str(data), "--embedder", "hash"])
    reports = data / "raw" / "reports.csv"
    before = reports.stat().st_mtime_ns
    assert warm_up.main(["--data", str(data), "--embedder", "hash"]) == 0
    assert reports.stat().st_mtime_ns == before
