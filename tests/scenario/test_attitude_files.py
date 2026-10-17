# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the attitude files: the body's attitude and each articulation's
angle, written as ECSV.

The quaternions are checked against the geometry, not against the code that
made them: read back as the header says, `+z` points at the Earth's centre in
nadir, and `-z` at the sun in sun pointing.
"""

import numpy as np
import pytest
from astropy.coordinates import CartesianRepresentation
from astropy.table import QTable, Table
from scipy.spatial.transform import Rotation

from quicksat import u
from quicksat.scenario import attitude_files
from quicksat.scenario.attitude import attitude_names
from quicksat.scenario.attitude_files import (
    QUATERNION_NOTES,
    articulation_file,
    write_attitude_files,
)
from quicksat.scenario.viewer import scenario_data


def unit_rows(vectors: np.ndarray) -> np.ndarray:
    """Each row scaled to unit length."""
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def test_the_quaternions_turn_body_axes_into_gcrs_as_the_header_says(run, tmp_path):
    paths = write_attitude_files(run, tmp_path)
    # without a model, there is the attitude file alone
    assert [path.name for path in paths] == ["attitude.ecsv"]
    table = QTable.read(paths[0], format="ascii.ecsv")
    assert (
        table.meta
        == {
            "scenario_file": "scenario.yaml",
            "epoch": run.times[0].utc.isot,
            "time_scale": "utc",
            "frame": "GCRS",
        }
        | QUATERNION_NOTES
    )
    assert table["time"].unit == u.s

    turns = Rotation.from_quat(
        np.column_stack([table[q] for q in ("qx", "qy", "qz", "qw")])
    )
    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    position = cartesian.xyz.to_value(u.km).T
    nadir = unit_rows(-position)
    sun = unit_rows(run.sun.xyz.to_value(u.km).T - position)
    attitude = np.asarray(table["attitude"])
    for name, axis, direction in (
        ("nadir", [0, 0, 1], nadir),
        ("sun pointing", [0, 0, -1], sun),
    ):
        rows = attitude == name
        assert rows.sum() > 100
        error = np.linalg.norm(turns[rows].apply(axis) - direction[rows], axis=1)
        assert error.max() < 1e-8


def test_the_attitude_column_marks_where_the_body_turns_at_once(
    run, slew_run, tmp_path
):
    def read(a_run, name):
        path = write_attitude_files(a_run, tmp_path / name)[0]
        table = Table.read(path, format="ascii.ecsv")
        q = np.column_stack([table[q] for q in ("qx", "qy", "qz", "qw")])
        turns = Rotation.from_quat(q[:-1]).inv() * Rotation.from_quat(q[1:])
        return np.asarray(table["attitude"]), np.degrees(turns.magnitude())

    # without slews, the body jumps where the attitude changes, and only there
    attitude, steps = read(run, "instant")
    changes = attitude[1:] != attitude[:-1]
    assert changes.sum() > 5
    assert steps[changes].min() > 30 and steps[~changes].max() < 1
    # with slews, the changes go through slew, and the body never jumps
    attitude, steps = read(slew_run, "slews")
    assert set(attitude) == {"nadir", "sun pointing", "slew"}
    assert steps.max() < 10


def test_each_articulation_has_a_file_of_its_angles(articulated_run, tmp_path):
    paths = write_attitude_files(articulated_run, tmp_path)
    assert [path.name for path in paths] == [
        "attitude.ecsv",
        "articulation_wing_+y.ecsv",
        "articulation_wing_-y.ecsv",
    ]
    tables = {path.name: QTable.read(path, format="ascii.ecsv") for path in paths[1:]}
    tracking = tables["articulation_wing_+y.ecsv"]
    limited = tables["articulation_wing_-y.ecsv"]
    for table, name in ((tracking, "wing +y"), (limited, "wing -y")):
        expected = articulated_run.articulations[name].to_value(u.deg)
        assert np.abs(table["angle"].to_value(u.deg) - expected).max() <= 5e-7
    # the meta data gives the articulation as the scenario file writes it
    assert {
        key: tracking.meta[key]
        for key in ("articulation", "part", "axis", "point", "park")
    } == {
        "articulation": "wing +y",
        "part": "Wing +y",
        "axis": "+y",
        "point": ["-z", "sun"],
        "park": {"downlink": "45 deg"},
    }
    assert limited.meta["range"] == ["-30 deg", "60 deg"]
    # the wing parks in downlink, at 45 deg; the other never parks
    parked = np.asarray(tracking["parked"])
    assert parked.any() and not np.asarray(limited["parked"]).any()
    assert np.all(tracking["angle"][parked] == 45 * u.deg)


def test_a_rerun_writes_the_same_bytes(run, tmp_path):
    first = write_attitude_files(run, tmp_path / "first")[0].read_bytes()
    assert write_attitude_files(run, tmp_path / "second")[0].read_bytes() == first


def test_names_that_give_the_same_file_are_refused(run, tmp_path, monkeypatch):
    assert articulation_file("wing +y") == "articulation_wing_+y.ecsv"
    assert articulation_file("solar wing / A") == "articulation_solar_wing_A.ecsv"
    tables = {name: Table(meta={"articulation": name}) for name in ("wing a", "wing_a")}
    monkeypatch.setattr(attitude_files, "articulation_tables", lambda _: tables)
    with pytest.raises(ValueError, match="'wing a' and 'wing_a' would both be written"):
        write_attitude_files(run, tmp_path)


def test_the_viewer_gets_the_angles_the_rates_and_the_files(run, slew_run, tmp_path):
    attitude = scenario_data(run)["attitude"]
    names = attitude_names(run)
    rpy = np.array([attitude[key] for key in ("roll_deg", "pitch_deg", "yaw_deg")])
    # nadir, +z to nadir and -y to the orbit normal, is LVLH itself
    assert np.abs(rpy[:, names == "nadir"]).max() < 1e-3
    # without slews, an attitude change is instant: no rate across it
    rate = attitude["rate_deg_s"]
    changes = np.flatnonzero(names[1:] != names[:-1])
    assert changes.size and all(rate[k] is None for k in changes)
    assert rate[-1] is None and attitude["max_rate_deg_s"] is None
    # with slews, the rate is known everywhere, and the limits come along
    slewing = scenario_data(slew_run)["attitude"]
    assert None not in slewing["rate_deg_s"][:-1]
    assert (slewing["max_rate_deg_s"], slewing["max_acceleration_deg_s2"]) == (
        0.7,
        0.08,
    )
    # the files to download are the ones Python writes
    paths = write_attitude_files(run, tmp_path)
    assert attitude["files"] == {path.name: path.read_text() for path in paths}
