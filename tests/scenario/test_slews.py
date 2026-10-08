# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the slews between attitudes.

`slew_run` is the fixture scenario with slews at 0.7 deg/s and 0.08 deg/s2, and
20 s of settling. Each slew turns into the next activity's attitude before that
activity starts. The tests check where the slews fall, how long they take, and
that the body turns smoothly and no faster than the limit allows.
"""

import numpy as np
import pytest

from quicksat import Q_, u
from quicksat.orbit.attitude import rotation_angles
from quicksat.scenario.attitude import SLEW, body_rotations
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import SLEW_STARTS_EARLY, run_scenario

from .conftest import SLEW as SLEW_BLOCK

TARGET_RATE = Q_(0.07, "deg / s")
"""Allowance for the target attitude's own motion. Nadir turns with the orbit at
0.063 deg/s, so the body can turn that much faster than the slew alone."""


def peak_rate(run):
    """The fastest the body turns between two steps of the grid."""
    rotations = body_rotations(run)
    angles = np.degrees(rotation_angles(rotations[:-1], rotations[1:]))
    steps = np.diff((run.times - run.times[0]).to_value(u.s))
    return Q_(np.max(angles / steps), "deg / s")


def test_a_slew_comes_before_each_change_of_attitude(slew_run):
    changes = [
        index
        for index, (before, after) in enumerate(
            zip(slew_run.occurrences[:-1], slew_run.occurrences[1:], strict=True), 1
        )
        if before.activity.attitude != after.activity.attitude
    ]
    assert [window.into for window in slew_run.slews] == changes
    for window in slew_run.slews:
        occurrence = slew_run.occurrences[window.into]
        assert window.end == occurrence.start
        assert window.target == occurrence.activity.attitude
        assert occurrence.slew == window.duration


def test_each_slew_lasts_its_turn_and_its_settling(slew_run):
    slew = slew_run.scenario.slew
    for window in slew_run.slews:
        turn = Q_((window.turned - window.start).to_value(u.s), "s")
        settling = Q_((window.end - window.turned).to_value(u.s), "s")
        assert turn.value == pytest.approx(slew.turn_time(window.angle).value, abs=2e-3)
        assert settling.value == pytest.approx(20, abs=1e-3)


def test_the_attitude_row_shows_the_slews(slew_run):
    slewing = slew_run.attitude.find(SLEW)
    for window in slew_run.slews:
        assert window.interval in slewing
    assert set(slew_run.attitude.values()) == {"nadir", "sun pointing", SLEW}
    table = slew_run.activity_table
    durations = [window.duration.to_value(u.s) for window in slew_run.slews]
    assert table["slew [s]"].dropna().tolist() == pytest.approx(durations)


def test_the_body_turns_no_faster_than_the_limit(slew_run):
    assert peak_rate(slew_run) < slew_run.scenario.slew.max_rate + TARGET_RATE


def test_without_slews_the_body_jumps(run):
    # the same scenario with instant changes: the body turns tens of degrees in a step
    assert run.slews == []
    assert run.activity_table["slew [s]"].isna().all()
    assert peak_rate(run) > Q_(5, "deg / s")


def test_a_slew_longer_than_the_activity_before_starts_early(data_dir):
    # the nadir activity lasts a minute, and the slew out of it takes over 3 min
    text = (data_dir / "scenario.yaml").read_text().split("activities:")[0]
    text += (
        "activities:\n"
        "  - [eclipse entry - 1 min, sun pointing, idle]\n"
        "  - [eclipse entry, nadir, idle]\n"
        "  - [eclipse exit, sun pointing, idle]\n"
    ) + SLEW_BLOCK
    run = run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))
    flagged = [o for o in run.occurrences if SLEW_STARTS_EARLY in o.statuses]
    assert flagged
    assert all(o.activity.trigger.text == "eclipse exit" for o in flagged)
    # the early slew starts partway through the one before, and the body still
    # turns smoothly
    assert run.scenario.slew is not None
    assert peak_rate(run) < run.scenario.slew.max_rate + TARGET_RATE
