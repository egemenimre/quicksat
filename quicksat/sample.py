# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Copy quicksat's sample into a folder, so that a user who installed quicksat with
pip has files to start from.

The sample is not in the package. It is in the repository on GitHub, in
`sample/`, with its data, its notebooks, and the viewers and editor pages written
from them. `copy_sample` downloads the repository's archive for the installed
version's tag, such as `v0.1.0`, and extracts `sample/` from it. When that tag has
no archive, as for a development version, it takes `master` instead, and says so.
A local copy of the repository, as a folder or as its zip, serves when there is no
network connection.

"""

import io
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from quicksat import __version__

REPOSITORY = "https://github.com/egemenimre/quicksat"
"""The repository on GitHub that holds the sample."""

SAMPLE_FOLDER = "sample"
"""The repository's folder that is copied."""

_TIMEOUT = 60
"""Seconds to wait for GitHub before giving up."""


def archive_url(ref: str) -> str:
    """
    The address of the repository's zip archive at a tag or a branch.

    Parameters
    ----------
    ref : str
        A tag, such as `v0.1.0`, or a branch, such as `master`

    Returns
    -------
    str
        The archive's address on GitHub
    """
    kind = "heads" if ref == "master" else "tags"
    return f"{REPOSITORY}/archive/refs/{kind}/{ref}.zip"


def download_archive(version: str = __version__) -> tuple[bytes, list[str]]:
    """
    Download the repository's archive for a version, or for `master` if it has none.

    Parameters
    ----------
    version : str, optional
        The quicksat version, the installed one by default

    Returns
    -------
    bytes
        The zip archive
    list of str
        Warnings, such as the fall back to `master`

    Raises
    ------
    OSError
        If GitHub cannot be reached, or has neither archive
    """
    tag = f"v{version}"
    try:
        return _download(archive_url(tag)), []
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        # the error holds GitHub's response, which is not read again
        error.close()
    warning = (
        f"GitHub has no tag {tag} for this version of quicksat, so the sample is "
        "taken from master. It may not match the installed code."
    )
    return _download(archive_url("master")), [warning]


def _download(url: str) -> bytes:
    """Read the whole of `url`."""
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:
        return response.read()


def extract_sample(archive: zipfile.ZipFile, folder: Path) -> list[Path]:
    """
    Write the archive's `sample/` folder into `folder`.

    The archive is the repository's, as GitHub gives it: every path starts with
    one top folder, such as `quicksat-0.1.0/`. `sample/` sits below it.

    Parameters
    ----------
    archive : zipfile.ZipFile
        The repository's archive
    folder : Path
        The folder to write into. It must not hold anything yet.

    Returns
    -------
    list of Path
        The files written

    Raises
    ------
    ValueError
        If the archive has no `sample/` folder, or a path that leaves it
    """
    members = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = PurePosixPath(info.filename).parts
        if len(parts) < 3 or parts[1] != SAMPLE_FOLDER:
            continue
        inner = parts[2:]
        if any(part in ("", ".", "..") for part in inner) or ":" in inner[0]:
            raise ValueError(f"the archive holds an unsafe path: {info.filename}")
        members[info.filename] = Path(*inner)
    if not members:
        raise ValueError(f"the archive has no {SAMPLE_FOLDER}/ folder")
    written = []
    for name, relative in members.items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(name) as source, open(target, "wb") as sink:
            shutil.copyfileobj(source, sink)
        written.append(target)
    return written


def copy_sample(
    folder: str | Path, source: str | Path | None = None
) -> tuple[list[Path], list[str]]:
    """
    Copy the sample into `folder`, from GitHub or from a local copy.

    Parameters
    ----------
    folder : str or Path
        The folder to copy into. It is made if missing, and must be empty if not.
    source : str or Path, optional
        A local copy of the repository: its folder, or its zip archive as GitHub
        gives it. By default, the archive is downloaded from GitHub.

    Returns
    -------
    list of Path
        The files written
    list of str
        Warnings, such as the fall back to `master`

    Raises
    ------
    FileExistsError
        If `folder` holds anything
    OSError
        If the archive cannot be downloaded or read
    ValueError
        If the source holds no sample
    """
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise FileExistsError(f"{folder} is not empty, so nothing was copied")
    if source is not None and Path(source).is_dir():
        sample = Path(source) / SAMPLE_FOLDER
        if not sample.is_dir():
            raise ValueError(f"{source} has no {SAMPLE_FOLDER}/ folder")
        shutil.copytree(sample, folder, dirs_exist_ok=True)
        return sorted(path for path in folder.rglob("*") if path.is_file()), []
    if source is None:
        data, warnings = download_archive()
    else:
        data, warnings = Path(source).read_bytes(), []
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ValueError(f"the archive is not a zip file: {error}") from error
    with archive:
        return extract_sample(archive, folder), warnings
