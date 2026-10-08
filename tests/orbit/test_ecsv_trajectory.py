# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for trajectory files in ECSV: writing, reading back, and refusing.

The states come from the fixture TLE through SGP4. A file written and read back
must give them again, in every frame, to the rounding the writer keeps.
"""

import numpy as np
import pytest
from astropy.table import Column, Table

from quicksat import Q_, u
from quicksat.orbit.ecsv_trajectory import (
    COLUMNS,
    read_ecsv_trajectory,
    write_ecsv_trajectory,
)
from quicksat.orbit.trajectory import FRAMES

from .conftest import vectors


@pytest.mark.parametrize("frame", list(FRAMES))
def test_a_file_reads_back_in_any_frame(tle, tmp_path, frame):
    state = tle.states(tle.epoch + Q_(np.arange(0, 1800, 60.0), "s"))
    path = write_ecsv_trajectory(tmp_path / "leo.ecsv", state, frame=frame, name="LEO")
    trajectory = read_ecsv_trajectory(path)
    found, found_velocity = vectors(trajectory.states(state.obstime))
    expected, expected_velocity = vectors(state)
    # the file keeps a millimetre and a micrometre a second
    assert np.linalg.norm(found - expected, axis=0).max() < 1.0
    assert np.linalg.norm(found_velocity - expected_velocity, axis=0).max() < 0.002
    assert (trajectory.name, trajectory.frame, trajectory.file) == (
        "LEO",
        frame,
        "leo.ecsv",
    )
    assert trajectory.sample_count == 30


def test_a_written_file_counts_seconds_from_its_epoch(tle, tmp_path):
    state = tle.states(tle.epoch + Q_(np.arange(0, 600, 60.0), "s"))
    text = write_ecsv_trajectory(tmp_path / "leo.ecsv", state).read_text()
    assert "- {name: time, unit: s, datatype: float64}" in text
    assert "{epoch: '2026-10-01T00:00:00.000'}" in text
    assert "__serialized_columns__" not in text
    rows = [line for line in text.splitlines() if not line.startswith("#")]
    assert rows[0] == "time x y z vx vy vz"
    assert rows[1].startswith("0.0 ")
    assert rows[2].startswith("60.0 ")


def table_of(
    tle, units=None, labels=None, meta=None, drop=(), offsets=None, header=True
) -> Table:
    """
    A trajectory table in GCRS from SGP4, in the file's layout. `units` converts
    a column to another unit. `labels` only names another unit, or none.
    """
    offsets = np.arange(0, 600, 60.0) if offsets is None else np.asarray(offsets)
    position, velocity = vectors(tle.states(tle.epoch + Q_(offsets, "s")))
    values = {"time": Q_(offsets, "s")}
    values |= dict(zip(("x", "y", "z"), Q_(position, "mm"), strict=True))
    values |= dict(zip(("vx", "vy", "vz"), Q_(velocity, "mm/s"), strict=True))
    units = COLUMNS | (units or {})
    labels = units | (labels or {})
    columns = [
        Column(values[name].to_value(units[name]), name=name, unit=labels[name])
        for name in COLUMNS
        if name not in drop
    ]
    fields = {"epoch": tle.epoch.utc.isot, "time_scale": "utc", "frame": "gcrs"}
    return Table(columns, meta=(fields | (meta or {})) if header else {})


def test_a_file_in_other_units_and_a_lower_case_frame_reads(tle, tmp_path):
    path = tmp_path / "metres.ecsv"
    units = {"time": u.min, "x": u.m, "y": u.m, "z": u.m, "vx": u.m / u.s}
    table_of(tle, units=units).write(path, format="ascii.ecsv")
    trajectory = read_ecsv_trajectory(path)
    times = tle.epoch + Q_([0.0, 300.0], "s")
    found, _ = vectors(trajectory.states(times))
    expected, _ = vectors(tle.states(times))
    assert np.allclose(found, expected, atol=1e-3)
    assert trajectory.frame == "gcrs"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"meta": {"frame": "ICRS"}}, "solar system's barycentre"),
        ({"meta": {"frame": "HCRS"}}, "'HCRS' is not read"),
        ({"meta": {"time_scale": "local"}}, "time scale 'local'"),
        ({"meta": {"epoch": "yesterday"}}, "the epoch is not a time"),
        ({"drop": ("vz",)}, "no 'vz' column"),
        ({"labels": {"x": None}}, "'x' column has no unit"),
        ({"labels": {"y": u.s}}, "not a unit of length"),
        ({"offsets": [0, 60, 120, 100, 240, 300, 360]}, "must rise"),
        ({"offsets": [0]}, "at least 2 samples"),
        ({"header": False}, "the header has no epoch, time_scale, frame"),
    ],
)
def test_a_file_that_cannot_be_read_is_refused(tle, tmp_path, change, message):
    path = tmp_path / "bad.ecsv"
    table_of(tle, **change).write(path, format="ascii.ecsv")
    with pytest.raises(ValueError, match=message):
        read_ecsv_trajectory(path)


def test_a_short_file_reads_with_a_lower_degree_and_a_warning(tle, tmp_path):
    path = tmp_path / "short.ecsv"
    table_of(tle, offsets=[0, 60, 120]).write(path, format="ascii.ecsv")
    with pytest.warns(UserWarning, match="degree 2 instead of 5"):
        trajectory = read_ecsv_trajectory(path)
    assert trajectory.sample_count == 3
    assert trajectory.format == "ECSV"


def test_a_plain_csv_or_no_file_is_refused(tmp_path):
    plain = tmp_path / "plain.csv"
    plain.write_text("time,x,y,z,vx,vy,vz\n0,7000,0,0,0,7.5,0\n")
    with pytest.raises(ValueError, match="not an ECSV table"):
        read_ecsv_trajectory(plain)
    with pytest.raises(FileNotFoundError):
        read_ecsv_trajectory(tmp_path / "nowhere.ecsv")
