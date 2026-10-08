# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for trajectory files in CCSDS OEM, in KVN.

`data/oem_blue_book_example.kvn` is the example of figure 5-1 of CCSDS
502.0-B-2: two segments around Mars, the second after a manoeuvre.
`data/oem_selene.kvn` is an abbreviated ephemeris of SELENE around the Earth,
written by JAXA as an ODM version 2 test case, with covariance blocks. The rest
are written here from the fixture TLE, or changed line by line.
"""

import re

import numpy as np
import pytest
from astropy.time import Time

from quicksat import Q_
from quicksat.orbit.ecsv_trajectory import write_ecsv_trajectory
from quicksat.orbit.oem_trajectory import (
    OEM_FRAMES,
    _parse,
    read_oem_trajectory,
    write_oem_trajectory,
)
from quicksat.orbit.trajectory_files import (
    ECSV,
    OEM,
    read_trajectory_file,
    trajectory_format,
)

from .conftest import vectors

_EPOCH = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+")
"""A date in an OEM, as the writer writes it."""


@pytest.fixture
def written(tle, tmp_path):
    """Ten minutes of the fixture TLE, written as an OEM in EME2000."""
    state = tle.states(tle.epoch + Q_(np.arange(0, 600, 60.0), "s"))
    path = write_oem_trajectory(
        tmp_path / "leo.oem", state, name="LEO", creation_date=tle.epoch
    )
    return path, state


def rewritten(path, change) -> str:
    """A changed copy of an OEM's text, saved next to it."""
    copy = path.with_name("changed.oem")
    copy.write_text(change(path.read_text()))
    return str(copy)


# ---------------------------------------------------------------- The examples


def test_the_blue_book_example_parses_into_two_segments(data_dir):
    path = data_dir / "oem_blue_book_example.kvn"
    header, segments = _parse(path.read_text(), path)
    assert header["CCSDS_OEM_VERS"][0] == "2.0"
    assert header["ORIGINATOR"][0] == "NASA/JPL"
    assert [len(segment.epochs) for segment in segments] == [3, 3]
    assert segments[1].meta["USEABLE_START_TIME"][0] == "1996-12-28T22:08:02.5"
    # the comments around the data are skipped, and the leading zero is read
    assert segments[1].values[0][1] == -63.042


def test_an_orbit_around_mars_is_refused(data_dir):
    with pytest.raises(ValueError, match="line 8: CENTER_NAME = MARS BARYCENTER"):
        read_oem_trajectory(data_dir / "oem_blue_book_example.kvn")


def test_selene_reads_its_two_segments_and_skips_the_covariance(data_dir):
    with pytest.warns(UserWarning, match="degree 2 instead of 5"):
        trajectory = read_trajectory_file(data_dir / "oem_selene.kvn")
    assert (trajectory.name, trajectory.frame, trajectory.originator) == (
        "SELENE",
        "EME2000",
        "JAXA",
    )
    assert (trajectory.format, trajectory.segment_count) == (OEM, 2)
    assert trajectory.sample_count == 6
    assert trajectory.start.utc.isot == "2007-09-14T10:43:00.000"
    assert trajectory.end.utc.isot == "2007-09-15T10:45:00.000"
    with pytest.raises(ValueError, match="crosses a gap"):
        trajectory.check_covers(trajectory.start, trajectory.end)


# ---------------------------------------------------------------- Round trips


@pytest.mark.parametrize("frame", [*OEM_FRAMES, "ITRF2000", "ITRF-97"])
def test_a_written_file_reads_back_in_any_frame(tle, tmp_path, frame):
    state = tle.states(tle.epoch + Q_(np.arange(0, 1800, 60.0), "s"))
    path = write_oem_trajectory(tmp_path / "leo.oem", state, frame=frame)
    trajectory = read_oem_trajectory(path)
    found, found_velocity = vectors(trajectory.states(state.obstime))
    expected, expected_velocity = vectors(state)
    # the file keeps a millimetre and a micrometre a second
    assert np.linalg.norm(found - expected, axis=0).max() < 1.0
    assert np.linalg.norm(found_velocity - expected_velocity, axis=0).max() < 0.002
    assert trajectory.frame == frame
    assert (trajectory.originator, trajectory.segment_count) == ("quicksat", 1)


def test_the_writer_writes_the_same_file_twice(written, tmp_path):
    path, state = written
    again = write_oem_trajectory(
        tmp_path / "again.oem", state, name="LEO", creation_date=state.obstime[0]
    )
    assert again.read_text() == path.read_text()
    assert path.read_text().startswith(
        "CCSDS_OEM_VERS = 2.0\nCREATION_DATE = 2026-10-01T00:00:00\n"
    )


def retimed(text: str, system: str) -> str:
    """An OEM's dates, written again in another time system."""

    def convert(match: re.Match) -> str:
        utc = Time(match.group(0), scale="utc")
        if system == "GPS":
            time = Time(utc.tai - Q_(19, "s"), precision=6)
        else:
            time = Time(getattr(utc, system.lower()), precision=6)
        return str(time.isot)

    text = _EPOCH.sub(convert, text)
    return text.replace("TIME_SYSTEM = UTC", f"TIME_SYSTEM = {system}")


@pytest.mark.parametrize("system", ["TT", "TAI", "GPS", "TDB"])
def test_each_time_system_gives_the_same_states(written, system):
    path, state = written
    other = read_oem_trajectory(rewritten(path, lambda text: retimed(text, system)))
    found, _ = vectors(other.states(state.obstime))
    expected, _ = vectors(state)
    assert np.linalg.norm(found - expected, axis=0).max() < 1.0


def day_of_year(text: str) -> str:
    """An OEM's dates as days of the year, each with a Z."""

    def convert(match: re.Match) -> str:
        time = Time(match.group(0), scale="utc", precision=6)
        year, day, clock = str(time.yday).split(":", 2)
        return f"{year}-{day}T{clock}Z"

    return _EPOCH.sub(convert, text)


def with_accelerations(text: str) -> str:
    """An OEM with three accelerations on each data line."""
    return re.sub(r"^(\d{4}-.*)$", r"\1 0.001 0.002 0.003", text, flags=re.MULTILINE)


@pytest.mark.parametrize("change", [day_of_year, with_accelerations])
def test_days_of_the_year_and_accelerations_read(written, change):
    path, state = written
    other = read_oem_trajectory(rewritten(path, change))
    found, _ = vectors(other.states(state.obstime))
    expected, _ = vectors(state)
    assert np.linalg.norm(found - expected, axis=0).max() < 1.0


# ---------------------------------------------------------------- Broken files


def first_data_line(text: str) -> str:
    """The first data line of an OEM."""
    return next(line for line in text.splitlines() if line[:4].isdigit())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda t: t.replace("META_STOP\n", ""),
            r"line \d+: a data line inside the metadata",
        ),
        (lambda t: t[: t.index("META_STOP")], "ends with no META_STOP"),
        (
            lambda t: t.replace("CCSDS_OEM_VERS = 2.0", "CCSDS_OEM_VERS = 4.0"),
            "line 1: OEM version 4.0",
        ),
        (
            lambda t: t.replace("CCSDS_OEM_VERS = 2.0\n", ""),
            "line 1: an OEM starts with",
        ),
        (
            lambda t: t.replace("OBJECT_NAME = LEO", "OBJECT_NAME LEO"),
            r"line \d+: expected KEY = value",
        ),
        (
            lambda t: t.replace("CENTER_NAME = EARTH\n", ""),
            "the metadata has no CENTER_NAME",
        ),
        (
            lambda t: t.replace("REF_FRAME = EME2000", "REF_FRAME = GRC"),
            "change REF_FRAME to ITRF",
        ),
        (
            lambda t: t.replace("REF_FRAME = EME2000", "REF_FRAME = MCI"),
            "REF_FRAME = MCI is not read",
        ),
        (
            lambda t: t.replace(
                "REF_FRAME = EME2000",
                "REF_FRAME = EME2000\nREF_FRAME_EPOCH = 2026-10-01T00:00:00",
            ),
            "REF_FRAME_EPOCH is not read",
        ),
        (
            lambda t: t.replace("TIME_SYSTEM = UTC", "TIME_SYSTEM = MET"),
            "TIME_SYSTEM = MET is not read",
        ),
        (
            lambda t: t.replace(
                first_data_line(t), " ".join(first_data_line(t).split()[:6])
            ),
            r"line \d+: a data line holds an epoch and 6 numbers",
        ),
        (
            lambda t: t.replace(
                first_data_line(t), "2026-13-45T00:00:00" + first_data_line(t)[26:]
            ),
            r"line \d+: '2026-13-45T00:00:00' is not an epoch",
        ),
        (
            lambda t: t.replace(
                "STOP_TIME = 2026-10-01T00:09:00.000000",
                "STOP_TIME = 2026-10-01T00:08:00",
            ),
            r"line \d+: the epoch lies outside START_TIME and STOP_TIME",
        ),
        (
            lambda t: t.replace(
                "2026-10-01T00:02:00.000000 ", "2026-10-01T00:00:30.000000 "
            ),
            r"line \d+: the epochs must rise",
        ),
        (
            lambda t: t.replace(
                "META_STOP", "USEABLE_START_TIME = 2026-09-30T23:59:00\nMETA_STOP"
            ),
            "the useable span reaches past",
        ),
        (
            lambda t: (
                t
                + "COVARIANCE_START\nEPOCH = 2026-10-01T00:00:00\nCOVARIANCE_STOP\n"
                + first_data_line(t)
                + "\n"
            ),
            r"line \d+: a data line after the covariance",
        ),
    ],
)
def test_a_broken_file_is_refused_with_its_line(written, change, message):
    path, _ = written
    with pytest.raises(ValueError, match=message):
        read_oem_trajectory(rewritten(path, change))


# ---------------------------------------------------------------- Telling formats apart


def test_the_format_is_told_from_the_first_line(written, tle, tmp_path):
    path, state = written
    ecsv = write_ecsv_trajectory(tmp_path / "leo.ecsv", state)
    assert trajectory_format(path) == OEM
    assert trajectory_format(ecsv) == ECSV
    assert read_trajectory_file(ecsv).format == ECSV
    xml = tmp_path / "leo.xml"
    xml.write_text('<?xml version="1.0"?>\n<oem/>\n')
    with pytest.raises(ValueError, match="an XML OEM is not read"):
        trajectory_format(xml)
    plain = tmp_path / "leo.txt"
    plain.write_text("time,x,y,z\n")
    with pytest.raises(ValueError, match="not a trajectory file quicksat reads"):
        trajectory_format(plain)
    with pytest.raises(FileNotFoundError):
        trajectory_format(tmp_path / "nowhere.oem")
