from pathlib import Path

import pytest

from health_tools.utils.atomic_file import atomic_write_text, current_revision, read_text_revision


def test_read_text_revision_hashes_original_utf8_bytes(tmp_path: Path):
    path = tmp_path / "sample.yaml"
    path.write_bytes(b"name: sample\r\n")

    source, revision = read_text_revision(path)

    assert source == "name: sample\r\n"
    assert revision == "282a1affa64ff0676618498481ba155b709ec7fb6f37ac3c49b1ed4602ec6bcc"
    path.write_bytes(b"name: sample\n")
    assert current_revision(path) != revision


def test_atomic_write_replaces_content_and_leaves_no_temporary_file(tmp_path: Path):
    path = tmp_path / "sample.yaml"
    path.write_text("old: true\n", encoding="utf-8")

    atomic_write_text(path, "new: true\n")

    assert path.read_text(encoding="utf-8") == "new: true\n"
    assert list(tmp_path.glob(".sample.yaml.*.tmp")) == []


def test_atomic_write_cleans_temporary_file_when_replace_fails(monkeypatch, tmp_path: Path):
    path = tmp_path / "sample.yaml"

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr("health_tools.utils.atomic_file.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(path, "new: true\n")

    assert not path.exists()
    assert list(tmp_path.glob(".sample.yaml.*.tmp")) == []
