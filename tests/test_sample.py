# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""Tests for `quicksat.sample` and `python -m quicksat init`, with no network."""

import io
import urllib.error
import zipfile
from email.message import Message
from pathlib import Path

import pytest

from quicksat import sample
from quicksat.__main__ import main

REPO = Path(__file__).parents[1]

FILES = {
    "sample/power/data/scenario.yaml": b"duration: 1 orbit\n",
    "sample/power/output/power_viewer.html": b"<html></html>",
    "sample/sizing/mass_budget.ipynb": b"{}",
}


def _archive(files: dict[str, bytes], top: str = "quicksat-0.1.0") -> bytes:
    """A zip laid out as GitHub's archive of the repository."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{top}/README.md", b"readme")
        archive.writestr(f"{top}/sample/", b"")
        for name, data in files.items():
            archive.writestr(f"{top}/{name}", data)
    return buffer.getvalue()


def _written(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }


def _expected() -> dict[str, bytes]:
    return {name.removeprefix("sample/"): data for name, data in FILES.items()}


def test_the_archive_urls():
    assert sample.archive_url("v0.1.0") == (
        "https://github.com/egemenimre/quicksat/archive/refs/tags/v0.1.0.zip"
    )
    assert sample.archive_url("master") == (
        "https://github.com/egemenimre/quicksat/archive/refs/heads/master.zip"
    )


def test_only_the_sample_is_copied_from_a_zip(tmp_path):
    zip_file = tmp_path / "quicksat.zip"
    zip_file.write_bytes(_archive(FILES))
    files, warnings = sample.copy_sample(tmp_path / "new", zip_file)
    assert _written(tmp_path / "new") == _expected()
    assert len(files) == len(FILES) and warnings == []


def test_the_sample_is_copied_from_a_folder(tmp_path):
    for name, data in FILES.items():
        path = tmp_path / "repo" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    sample.copy_sample(tmp_path / "new", tmp_path / "repo")
    assert _written(tmp_path / "new") == _expected()


def test_the_repository_sample_holds_every_domain(tmp_path):
    sample.copy_sample(tmp_path, REPO)
    for domain in ("sizing", "scenario", "power"):
        assert (tmp_path / domain / "data").is_dir()


def test_a_folder_with_files_is_refused(tmp_path):
    (tmp_path / "mine.txt").write_text("keep me")
    with pytest.raises(FileExistsError):
        sample.copy_sample(tmp_path, REPO)
    assert _written(tmp_path) == {"mine.txt": b"keep me"}


def test_a_path_out_of_the_folder_is_refused(tmp_path):
    zip_file = tmp_path / "bad.zip"
    zip_file.write_bytes(_archive({"sample/../../escape.txt": b"x"}))
    with pytest.raises(ValueError, match="unsafe path"):
        sample.copy_sample(tmp_path / "new", zip_file)
    assert not (tmp_path / "escape.txt").exists()


def test_an_archive_without_a_sample_is_refused(tmp_path):
    zip_file = tmp_path / "empty.zip"
    zip_file.write_bytes(_archive({}))
    with pytest.raises(ValueError, match="no sample/ folder"):
        sample.copy_sample(tmp_path / "new", zip_file)


def test_the_installed_version_tag_is_downloaded(tmp_path, monkeypatch):
    asked = []

    def download(url):
        asked.append(url)
        return _archive(FILES)

    monkeypatch.setattr(sample, "_download", download)
    _, warnings = sample.copy_sample(tmp_path)
    assert asked == [sample.archive_url(f"v{sample.__version__}")]
    assert warnings == []
    assert _written(tmp_path) == _expected()


def test_a_missing_tag_falls_back_to_master(tmp_path, monkeypatch):
    asked = []

    def download(url):
        asked.append(url)
        if "/tags/" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", Message(), None)
        return _archive(FILES, top="quicksat-master")

    monkeypatch.setattr(sample, "_download", download)
    _, warnings = sample.copy_sample(tmp_path)
    assert asked[-1] == sample.archive_url("master")
    assert len(warnings) == 1 and "master" in warnings[0]
    assert _written(tmp_path) == _expected()


def test_the_command_copies_and_prints_the_next_steps(tmp_path, capsys):
    main(["init", str(tmp_path / "new"), "--from", str(REPO)])
    out = capsys.readouterr().out
    assert out.startswith("Copied ")
    assert "python -m quicksat.editor serve" in out


def test_the_command_stops_on_a_folder_with_files(tmp_path, capsys):
    (tmp_path / "mine.txt").write_text("keep me")
    with pytest.raises(SystemExit) as stop:
        main(["init", str(tmp_path), "--from", str(REPO)])
    assert stop.value.code == 1
    assert capsys.readouterr().err.startswith("error: ")
