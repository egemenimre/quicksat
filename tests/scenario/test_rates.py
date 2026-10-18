# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the turn rate within each activity, against the slew capacity.

`slew_run` keeps every attitude within the limits: nadir and sun pointing turn
at about the orbit's 0.063 deg/s. With the limits set below that, nadir passes
them, which tests the check without a ground target.
"""

import dataclasses

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from quicksat import u
from quicksat.orbit.attitude import body_rates
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import scenario_data

from .conftest import SLOW


def test_a_steady_spin_has_its_rate_and_no_acceleration():
    seconds = np.arange(0.0, 60.0, 10.0)
    rotations = Rotation.from_rotvec(np.outer(np.radians(0.5) * seconds, [0, 0, 1]))
    rates, accelerations = body_rates(rotations.as_matrix(), seconds)
    assert np.degrees(rates) == pytest.approx(np.full(5, 0.5))
    assert accelerations == pytest.approx(np.zeros(4), abs=1e-15)


def test_a_change_of_axis_counts_as_acceleration():
    # 0.5 deg/s about z for a step, then about x: the rate holds, but the turn
    # vector changes by 0.5 * sqrt(2) deg/s over 10 s
    first = Rotation.from_rotvec([0, 0, np.radians(5)])
    second = first * Rotation.from_rotvec([np.radians(5), 0, 0])
    rotations = np.stack([np.eye(3), first.as_matrix(), second.as_matrix()])
    rates, accelerations = body_rates(rotations, np.array([0.0, 10.0, 20.0]))
    assert np.degrees(rates) == pytest.approx([0.5, 0.5])
    assert np.degrees(accelerations) == pytest.approx([0.5 * np.sqrt(2) / 10])


def test_a_time_with_no_orientation_has_no_rate_next_to_it():
    seconds = np.arange(0.0, 60.0, 10.0)
    rotations = Rotation.from_rotvec(np.outer(np.radians(0.5) * seconds, [0, 0, 1]))
    matrices = rotations.as_matrix()
    matrices[4:] = np.nan
    rates, accelerations = body_rates(matrices, seconds)
    assert np.degrees(rates[:3]) == pytest.approx(np.full(3, 0.5))
    assert np.isnan(rates[3:]).all()
    assert accelerations[:2] == pytest.approx(np.zeros(2), abs=1e-15)
    assert np.isnan(accelerations[2:]).all()
    # with no orientation at all, there is no rate at all
    rates, accelerations = body_rates(np.full((6, 3, 3), np.nan), seconds)
    assert np.isnan(rates).all()
    assert np.isnan(accelerations).all()


def test_within_the_limits_there_is_no_warning(slew_run, run):
    assert slew_run.rate_excesses == []
    assert slew_run.warnings == []
    # without a slew block there is nothing to check against
    assert run.warnings == []


@pytest.fixture(scope="module")
def slow_run(data_dir):
    """`scenario.yaml` with a slew rate limit below the orbit's rate."""
    text = (data_dir / "scenario.yaml").read_text() + SLOW
    return run_scenario(Scenario.from_yaml_text(text, data_dir))


def test_an_attitude_past_the_limit_gives_a_warning(slow_run):
    excesses = slow_run.rate_excesses
    attitudes = {excess.occurrence.activity.attitude for excess in excesses}
    assert "nadir" in attitudes
    for excess in excesses:
        assert excess.peak_rate.to_value(u.deg / u.s) > 0.05
        # the warning starts when the activity's own attitude does, after its slew
        assert excess.start >= excess.occurrence.start
        assert excess.start < excess.occurrence.end
    first = excesses[0]
    assert first.text.startswith(
        f"Tracking in {first.occurrence.activity.title} "
        f"({first.occurrence.activity.attitude}), starting "
        f"{first.start.utc.iso[:19]} UTC, exceeds the slew capacity."
    )
    assert "against the slew block's 0.05 deg/s and 0.08 deg/s2" in first.text
    assert slow_run.warnings == [excess.text for excess in excesses]


def test_the_slews_themselves_are_left_out(slow_run):
    # every slew turns faster than 0.05 deg/s, yet only the attitudes count:
    # nadir turns at the orbit's rate, about 0.063 deg/s
    for excess in slow_run.rate_excesses:
        assert excess.peak_rate.to_value(u.deg / u.s) < 0.07


def test_the_viewer_carries_the_warnings(slow_run, run):
    assert scenario_data(slow_run)["warnings"] == slow_run.warnings
    assert scenario_data(run)["warnings"] == []


def test_a_limit_left_out_is_never_passed(data_dir):
    # nadir turns at the orbit's 0.063 deg/s, so a rate limit left out but read
    # as zero would give a warning in every nadir activity
    text = (data_dir / "scenario.yaml").read_text().replace("3 orbits", "1 orbit")
    no_rate = "slew: {max_acceleration: 0.08 deg/s2, settling_time: 20 s}\n"
    run = run_scenario(Scenario.from_yaml_text(text + no_rate, data_dir))
    assert "nadir" in run.attitude.values()
    assert run.rate_excesses == []


def test_a_limit_left_out_is_not_named(slow_run):
    excess = dataclasses.replace(slow_run.rate_excesses[0], max_acceleration=None)
    assert excess.text.endswith("against the slew block's 0.05 deg/s.")
