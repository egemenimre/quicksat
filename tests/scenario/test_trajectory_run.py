# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for a scenario whose orbit comes from a trajectory file.

The file is written from the fixture TLE, at 60 s, in ITRS, from 10 min before
the run to 10 min after it. The run from it must match the run from the TLE:
the same occurrences, statuses and eclipses, to a few milliseconds. The period
measured from the file differs from SGP4's nodal period by under a millisecond,
so three orbits end within a few milliseconds of each other.
"""

import numpy as np
import pytest

from quicksat import Q_, u
from quicksat.orbit.ecsv_trajectory import write_ecsv_trajectory
from quicksat.orbit.tle import read_tle_file
from quicksat.orbit.trajectory import ASCENDING_NODES, Trajectory
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import VERSION, scenario_data

TOLERANCE_S = 5e-3
"""How far apart the two runs' times may be."""


def write_file(data_dir, folder, start_s, end_s, name="leo.ecsv"):
    """The fixture TLE's states, from and to these offsets from its epoch."""
    tle = read_tle_file(data_dir / "sso_510km.tle")
    offsets = np.arange(start_s, end_s + 60.0, 60.0)
    state = tle.states(tle.epoch + Q_(offsets, "s"))
    return write_ecsv_trajectory(folder / name, state, frame="ITRS", name="SSO 510")


def scenario_from(data_dir, folder, name="leo.ecsv", **replace):
    """The fixture scenario, with its orbit from a trajectory file."""
    text = (data_dir / "scenario.yaml").read_text()
    text = text.replace("tle_file: sso_510km.tle", f"trajectory_file: {name}")
    for old, new in replace.items():
        text = text.replace(old, new)
    return Scenario.from_yaml_text(text, base_dir=folder)


@pytest.fixture(scope="module")
def trajectory_run(data_dir, tmp_path_factory):
    """The fixture scenario, run from a trajectory file."""
    folder = tmp_path_factory.mktemp("trajectory")
    write_file(data_dir, folder, -600.0, 3 * 5700.0 + 600.0)
    return run_scenario(scenario_from(data_dir, folder))


def seconds(time, start) -> float:
    """A time in seconds from the start."""
    return float((time - start).to_value(u.s))


def test_the_path_is_taken_from_the_folder_of_the_file(data_dir, tmp_path):
    scenario = scenario_from(data_dir, tmp_path)
    assert scenario.orbit.trajectory_file == tmp_path / "leo.ecsv"


def test_the_run_from_the_file_matches_the_run_from_the_tle(run, trajectory_run):
    assert isinstance(trajectory_run.orbit, Trajectory)
    assert trajectory_run.orbit.period_method == ASCENDING_NODES
    assert trajectory_run.orbit.period.to_value(u.s) == pytest.approx(
        run.orbit.period.to_value(u.s), abs=1e-3
    )
    start = run.times[0]
    assert seconds(trajectory_run.times[-1], start) == pytest.approx(
        seconds(run.times[-1], start), abs=TOLERANCE_S
    )
    assert len(trajectory_run.occurrences) == len(run.occurrences)
    for found, expected in zip(
        trajectory_run.occurrences, run.occurrences, strict=True
    ):
        assert found.statuses == expected.statuses
        assert seconds(found.start, start) == pytest.approx(
            seconds(expected.start, start), abs=TOLERANCE_S
        )
        assert seconds(found.end, start) == pytest.approx(
            seconds(expected.end, start), abs=TOLERANCE_S
        )
    for found, expected in zip(trajectory_run.eclipses, run.eclipses, strict=True):
        for bound in ("lower", "upper"):
            assert seconds(getattr(found, bound), start) == pytest.approx(
                seconds(getattr(expected, bound), start), abs=TOLERANCE_S
            )


def test_the_viewer_names_the_file(trajectory_run):
    data = scenario_data(trajectory_run)
    orbit = data["orbit"]
    assert data["version"] == VERSION == 4
    assert orbit["tle"] is None
    assert orbit["name"] == "SSO 510"
    assert orbit["trajectory"]["file"] == "leo.ecsv"
    assert orbit["trajectory"]["frame"] == "ITRS"
    assert orbit["trajectory"]["period_from"] == ASCENDING_NODES
    assert orbit["period_s"] == pytest.approx(
        trajectory_run.orbit.period.to_value(u.s), abs=1e-3
    )


def test_a_run_outside_the_file_is_refused(data_dir, tmp_path):
    write_file(data_dir, tmp_path, 0.0, 3 * 5700.0)
    scenario = scenario_from(
        data_dir, tmp_path, **{"2026-10-01T00:00:00": "2026-10-02T00:00:00"}
    )
    with pytest.raises(ValueError, match="does not lie inside the trajectory"):
        run_scenario(scenario)


def test_a_file_shorter_than_an_orbit_needs_a_duration_in_time(data_dir, tmp_path):
    write_file(data_dir, tmp_path, 0.0, 3000.0)
    with pytest.raises(ValueError, match="less than one orbit"):
        run_scenario(scenario_from(data_dir, tmp_path))
    with pytest.warns(UserWarning, match="within 3 samples"):
        short = run_scenario(
            scenario_from(data_dir, tmp_path, **{"3 orbits": "30 min"})
        )
    assert seconds(short.times[-1], short.times[0]) == pytest.approx(1800.0)
