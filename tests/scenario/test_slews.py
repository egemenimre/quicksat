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
from quicksat.scenario.attitude import body_rotations
from quicksat.scenario.config import Scenario
from quicksat.scenario.events import SLEW_STARTS_EARLY
from quicksat.scenario.names import SLEW
from quicksat.scenario.run import run_scenario

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


def test_the_platform_mode_row_shows_the_slews(slew_run):
    # a slew takes the end of the activity before it: the platform's mode row
    # names the slew as the attitude row does
    platform = slew_run.mode["platform"]
    assert platform.find(SLEW) == slew_run.attitude.find(SLEW)
    activities = slew_run.scenario.activities
    modes = {activity.mode.platform for activity in activities}
    assert set(platform.values()) == modes | {SLEW}
    # the occurrences keep their activity's modes
    assert {o.activity.mode for o in slew_run.occurrences} == {
        a.mode for a in activities
    }


def test_the_payload_mode_carries_on_through_the_slews(slew_run):
    payload = slew_run.mode["payload"]
    assert SLEW not in payload.values()
    # through each turn, the payload stays in the mode of the activity it ends
    for window in slew_run.slews:
        before = slew_run.occurrences[window.into - 1].activity.mode.payload
        assert set(payload[window.interval].values()) == {before}


def test_an_activity_can_give_the_payload_its_own_mode_in_the_slew_into_it(data_dir):
    # the imaging activity asks for its mode in the turn into it: the payload
    # prepares there, and the other turns keep the mode of the activity before
    text = (data_dir / "scenario.yaml").read_text()
    text = text.replace(
        "{payload_mode: imaging, platform_mode: imaging}",
        "{payload_mode: imaging, platform_mode: imaging, "
        "payload_mode_in_slew: this_activity}",
    )
    run = run_scenario(Scenario.from_yaml_text(text + SLEW_BLOCK, base_dir=data_dir))
    payload, platform = run.mode["payload"], run.mode["platform"]
    into_imaging = 0
    for window in run.slews:
        after = run.occurrences[window.into].activity
        before = run.occurrences[window.into - 1].activity
        expected = after if after.title == "imaging" else before
        into_imaging += after.title == "imaging"
        assert set(payload[window.interval].values()) == {expected.mode.payload}
        assert set(platform[window.interval].values()) == {SLEW}
    assert into_imaging


def test_the_body_turns_no_faster_than_the_limit(slew_run):
    assert peak_rate(slew_run) < slew_run.scenario.slew.max_rate + TARGET_RATE


def test_without_slews_the_body_jumps(run):
    # the same scenario with instant changes: the body turns tens of degrees in a step
    assert run.slews == []
    assert SLEW not in run.mode["platform"].values()
    assert run.activity_table["slew [s]"].isna().all()
    assert peak_rate(run) > Q_(5, "deg / s")


def test_a_slew_longer_than_the_activity_before_starts_early(data_dir):
    # the nadir activity lasts a minute, and the slew out of it takes over 3 min
    text = (data_dir / "scenario.yaml").read_text().split("activities:")[0]
    text += (
        "activities:\n"
        "  - [sun before the eclipse, eclipse entry - 1 min, sun pointing, {payload_mode: idle, platform_mode: idle}]\n"
        "  - [last minute, eclipse entry, nadir, {payload_mode: idle, platform_mode: idle}]\n"
        "  - [eclipse, eclipse exit, sun pointing, {payload_mode: idle, platform_mode: idle}]\n"
    ) + SLEW_BLOCK
    run = run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))
    flagged = [o for o in run.occurrences if SLEW_STARTS_EARLY in o.statuses]
    assert flagged
    assert all(o.activity.trigger.text == "eclipse exit" for o in flagged)
    # the early slew starts partway through the one before, and the body still
    # turns smoothly
    assert run.scenario.slew is not None
    assert peak_rate(run) < run.scenario.slew.max_rate + TARGET_RATE


def test_a_slew_that_must_start_first_replaces_the_one_before(slow_run):
    occurrences, slews = slow_run.occurrences, slow_run.slews
    # in time order, and no two start together
    assert all(a.start < b.start for a, b in zip(slews[:-1], slews[1:], strict=True))
    changes = {
        index
        for index, (before, after) in enumerate(
            zip(occurrences[:-1], occurrences[1:], strict=True), 1
        )
        if before.activity.attitude != after.activity.attitude
    }
    replaced = changes - {window.into for window in slews}
    assert replaced
    for index in replaced:
        assert occurrences[index].slew is None
        # the slew after it starts before its activity does, and says so
        following = next(window for window in slews if window.into > index)
        assert following.start < occurrences[index].start
        assert SLEW_STARTS_EARLY in occurrences[following.into].statuses


def test_a_slew_keeps_its_way_round_while_its_target_moves_past_a_half_turn(
    slow_run,
):
    # quaternions more than 90 degrees apart are rotations more than a half turn
    # apart: in a slow slew, nadir moves that far before the turn ends
    assert any(window.path[0] @ window.path[-1] < 0 for window in slow_run.slews)
    # the way round chosen for the end alone flipped there, and the body jumped
    # at 7.2 deg/s
    assert peak_rate(slow_run) < Q_(1, "deg / s")
