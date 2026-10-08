# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for running a scenario.

The rules of the chain are tested on a made-up run of 100 min, with eclipses from
20 to 50 min and from 80 to 100 min. Inside them, the umbra runs from 22 to 48 min
and from 82 to 100 min, so each penumbra lasts 2 min. Every expected time follows
from those numbers. The orbit is tested on the runs of the fixture files.
"""

import numpy as np
import portion as P
import pytest
from astropy.tests.helper import assert_quantity_allclose
from astropy.time import Time

from quicksat import Q_, u
from quicksat.orbit.geometry import geodetic
from quicksat.orbit.tle import tle_states
from quicksat.scenario.config import Activity, Scenario
from quicksat.scenario.run import (
    CUT_AT_END,
    EVENT_NEVER_CAME,
    NEGATIVE_DURATION,
    OUTSIDE_CONSTRAINT,
    STATUS_OK,
    activity_table,
    find_events,
    next_event,
    resolve_activities,
    run_length,
    run_scenario,
    scenario_tle,
)
from quicksat.utils.intervals import labels_at, round_time

T0 = round_time(Time("2026-10-01T00:00:00", scale="utc"))
RUN = P.closedopen(T0, round_time(T0 + Q_(100, "min")))


def at(minutes):
    """A time that many minutes after the start of the made-up run."""
    return round_time(T0 + Q_(minutes, "min"))


def minutes(time):
    """Minutes from the start of the made-up run."""
    return float((time - T0).to_value(u.min))


ECLIPSES = P.closedopen(at(20), at(50)) | P.closedopen(at(80), at(100))
UMBRA = P.closedopen(at(22), at(48)) | P.closedopen(at(82), at(100))
ILLUMINATION = {
    "sunlit": RUN - ECLIPSES,
    "penumbra": ECLIPSES - UMBRA,
    "umbra": UMBRA,
    "eclipse": ECLIPSES,
}
ABOVE = {30.0: P.closedopen(at(10), at(40)) | P.closedopen(at(70), at(100))}
"""The time above each latitude: 30 deg is crossed going north at 10 and 70 min,
and going south at 40 min. No other latitude is ever reached."""


def resolve(*fields):
    """Resolve a list of activities, each given as its fields, on the made-up run."""
    activities = [Activity.from_fields(list(activity)) for activity in fields]

    def time_above(latitude):
        return ABOVE.get(float(latitude.to_value(u.deg)), P.empty())

    events = find_events(activities, RUN, ILLUMINATION, time_above)
    return resolve_activities(activities, RUN, events, ILLUMINATION)


def spans(occurrences):
    """Each occurrence's start and end, in minutes."""
    return [(round(minutes(o.start), 6), round(minutes(o.end), 6)) for o in occurrences]


# ---------------------------------------------------------------- The chain


def test_durations_chain_and_repeat_and_the_last_is_cut():
    occurrences = resolve(["30 min", "nadir", "a"], ["15 min", "nadir", "b"])
    assert spans(occurrences) == [(0, 30), (30, 45), (45, 75), (75, 90), (90, 100)]
    assert [o.repeat for o in occurrences] == [1, 1, 2, 2, 3]
    assert [o.number for o in occurrences] == [1, 2, 1, 2, 1]
    assert occurrences[-1].statuses == [CUT_AT_END]
    assert all(o.statuses == [STATUS_OK] for o in occurrences[:-1])


def test_an_event_ends_at_the_next_one_strictly_after_the_start():
    occurrences = resolve(["eclipse entry", "nadir", "a"])
    # the second starts at an entry, so it runs to the next one
    assert spans(occurrences) == [(0, 20), (20, 80), (80, 100)]


@pytest.mark.parametrize(
    ("trigger", "ends"),
    [
        ("eclipse entry", [20, 80]),
        ("umbra entry", [22, 82]),
        ("umbra exit", [48]),
        ("eclipse exit", [50]),
    ],
)
def test_each_shadow_edge(trigger, ends):
    occurrences = resolve([trigger, "nadir", "a"])
    found = [round(minutes(o.end), 6) for o in occurrences if not o.cut_at_end]
    assert found == ends


def test_the_penumbra_and_umbra_constraints():
    occurrences = resolve(
        ["eclipse entry", "nadir", "a", "sunlit"],
        ["umbra entry", "nadir", "b", "penumbra"],
        ["umbra exit", "nadir", "c", "umbra"],
        ["eclipse exit", "nadir", "d", "penumbra"],
    )
    assert spans(occurrences)[:4] == [(0, 20), (20, 22), (22, 48), (48, 50)]
    assert all(o.statuses == [STATUS_OK] for o in occurrences[:4])
    # a penumbra constraint over the whole eclipse misses the umbra's 26 min
    _, whole = resolve(
        ["eclipse entry", "nadir", "a"], ["eclipse exit", "nadir", "b", "penumbra"]
    )[:2]
    assert spans([whole]) == [(20, 50)]
    assert whole.outside == Q_(26, "min").to(u.s)


def test_an_offset_moves_the_end_after_the_event_is_found():
    occurrences = resolve(
        ["eclipse entry + 2 min", "nadir", "a"], ["eclipse exit - 5 min", "nadir", "b"]
    )
    assert spans(occurrences)[:2] == [(0, 22), (22, 45)]


@pytest.mark.parametrize(
    ("trigger", "ends"),
    [
        ("latitude 30 deg ascending", [10, 70]),
        ("latitude 30 deg descending", [40]),
        ("latitude 30 deg", [10, 40, 70]),
    ],
)
def test_a_latitude_crossing_by_direction(trigger, ends):
    occurrences = resolve([trigger, "nadir", "a"])
    found = [
        round(minutes(o.end), 6)
        for o in occurrences
        if not (o.cut_at_end or o.event_never_came)
    ]
    assert found == ends


def test_an_event_that_never_comes_runs_to_the_end():
    (occurrence,) = resolve(["latitude 60 deg", "nadir", "a"])
    assert spans([occurrence]) == [(0, 100)]
    assert occurrence.statuses == [EVENT_NEVER_CAME]


def test_an_event_that_does_not_come_again_is_cut_at_the_end():
    occurrences = resolve(["latitude 30 deg descending", "nadir", "a"])
    assert occurrences[-1].statuses == [CUT_AT_END]
    assert not occurrences[-1].event_never_came


def test_the_time_outside_a_constraint():
    occurrences = resolve(
        ["30 min", "nadir", "a", "sunlit"], ["30 min", "nadir", "b", "eclipse"]
    )
    # sunlit from 0 to 30 min, with the eclipse from 20; then eclipse from 30 to
    # 60 min, with the eclipse ending at 50
    assert occurrences[0].outside == Q_(10, "min").to(u.s)
    assert occurrences[1].outside == Q_(10, "min").to(u.s)
    assert occurrences[0].statuses == [OUTSIDE_CONSTRAINT]


def test_a_negative_duration_takes_no_time():
    occurrences = resolve(
        ["eclipse entry - 30 min", "nadir", "a"], ["30 min", "nadir", "b"]
    )
    first, second = occurrences[:2]
    assert spans([first]) == [(0, -10)]
    assert first.negative_duration
    assert first.statuses == [NEGATIVE_DURATION]
    assert first.interval.empty
    # the next one starts where the first started, and its end is not moved
    assert spans([second]) == [(0, 30)]


def test_a_negative_duration_shows_in_the_table():
    occurrences = resolve(
        ["eclipse entry - 30 min", "nadir", "a"], ["30 min", "nadir", "b"]
    )
    table = activity_table(occurrences)
    assert table.loc[0, "duration [min]"] == pytest.approx(-10)
    assert table.loc[0, "status"] == NEGATIVE_DURATION


def test_a_list_that_never_moves_on_stops_the_run():
    with pytest.raises(ValueError, match="never moves on"):
        resolve(["eclipse entry - 90 min", "nadir", "a"])


def test_next_event_takes_the_first_of_several_intervals():
    above, below = ABOVE[30.0], RUN - ABOVE[30.0]
    assert minutes(next_event((above, below), at(15))) == pytest.approx(40)
    assert next_event((P.empty(),), at(15)) is None


def test_the_time_above_a_latitude_is_found_once_for_all_directions():
    calls = []

    def time_above(latitude):
        calls.append(latitude)
        return ABOVE[30.0]

    activities = [
        Activity.from_fields([trigger, "nadir", "a"])
        for trigger in (
            "latitude 30 deg ascending",
            "latitude 30 deg",
            "latitude 30 deg descending + 1 min",
        )
    ]
    events = find_events(activities, RUN, ILLUMINATION, time_above)
    assert len(calls) == 1
    assert len(events) == 3


# ---------------------------------------------------------------- The orbit


def test_the_length_of_a_run_in_orbits(run):
    assert_quantity_allclose(
        run_length(run.scenario, run.tle), 3 * run.tle.nodal_period, rtol=1e-12
    )


def test_a_step_as_long_as_the_run_is_refused(data_dir):
    text = (data_dir / "scenario.yaml").read_text().replace("3 orbits", "0.001 orbits")
    scenario = Scenario.from_yaml_text(text, base_dir=data_dir)
    with pytest.raises(ValueError, match="step must be shorter than the run"):
        run_length(scenario, scenario_tle(scenario))


def test_the_grid_ends_exactly_at_the_end_of_the_run(run):
    offsets = (run.times - run.times[0]).to_value(u.s)
    assert np.allclose(np.diff(offsets)[:-1], 10.0)
    assert run.times[-1] == run.interval.upper
    assert offsets[-1] == pytest.approx(
        3 * run.tle.nodal_period.to_value(u.s), abs=1e-3
    )


def test_the_gantt_rows_cover_the_run(run):
    for row in (run.illumination, run.attitude, run.mode):
        assert row.domain() == run.interval
    assert run.eclipses | run.sunlit == run.interval
    assert (run.eclipses & run.sunlit).empty


def test_the_illumination_has_three_states(run):
    assert set(run.illumination.values()) == {"sunlit", "penumbra", "umbra"}
    assert run.umbra | run.penumbra == run.eclipses
    assert (run.umbra & run.penumbra).empty
    # each eclipse holds one umbra, with a penumbra of seconds on each side
    assert len(run.umbra) == len(run.eclipses)
    assert len(run.penumbra) == 2 * len(run.eclipses)
    for piece in run.penumbra:
        assert 5 < (piece.upper - piece.lower).to_value(u.s) < 15


def test_the_light_follows_the_illumination(run):
    states = labels_at(run.illumination, run.times[:-1])
    light = run.light[:-1]
    assert np.all(light[states == "sunlit"] == 1)
    assert np.all(light[states == "umbra"] == 0)
    assert np.all((light >= 0) & (light <= 1))


def test_the_umbra_triggers_on_the_orbit(data_dir):
    text = (data_dir / "scenario.yaml").read_text().split("activities:")[0]
    text += (
        "activities:\n  - [umbra entry, nadir, idle]\n  - [umbra exit, nadir, idle]\n"
    )
    run = run_scenario(Scenario.from_yaml_text(text, base_dir=data_dir))
    edges = [o.end for o in run.occurrences if not o.cut_at_end]
    umbra = list(run.umbra)
    assert edges[0] == umbra[0].lower
    assert edges[1] == umbra[0].upper


def test_each_occurrence_starts_where_the_one_before_ended(run):
    for before, after in zip(run.occurrences[:-1], run.occurrences[1:], strict=True):
        assert after.start == before.end
    assert run.occurrences[-1].end == run.interval.upper


def test_the_fixture_run_is_clean_but_for_its_last_activity(run):
    assert [o.statuses for o in run.occurrences[:-1]] == [[STATUS_OK]] * (
        len(run.occurrences) - 1
    )
    assert run.occurrences[-1].statuses == [CUT_AT_END]


def test_each_latitude_crossing_is_found_to_a_millisecond(run):
    millisecond = Q_(1, "ms")
    checked = 0
    for occurrence in run.occurrences:
        trigger = occurrence.activity.trigger
        if trigger.latitude is None or occurrence.cut_at_end:
            continue
        crossing = occurrence.end - (
            trigger.offset if trigger.offset is not None else Q_(0, "s")
        )
        times = round_time(crossing + np.array([-1, 1]) * millisecond)
        latitude, _ = geodetic(tle_states(run.tle, times, with_velocity=False))
        before, after = latitude.to_value(u.deg) - trigger.latitude.to_value(u.deg)
        assert before * after < 0
        if trigger.direction == "ascending":
            assert before < 0
        if trigger.direction == "descending":
            assert before > 0
        checked += 1
    assert checked >= 6


def test_ascending_nodes_come_a_whole_number_of_nodal_periods_apart(run):
    # the list repeats every two orbits here, so its nodes are two periods apart
    nodes = [
        o.end for o in run.occurrences if o.activity.trigger.text == "ascending node"
    ]
    gaps = np.diff([(node - run.times[0]).to_value(u.s) for node in nodes])
    period = run.tle.nodal_period.to_value(u.s)
    assert len(gaps) >= 1
    assert gaps == pytest.approx(np.round(gaps / period) * period, abs=2e-3)


def test_each_problem_has_its_own_status(problem_run):
    statuses = [o.statuses for o in problem_run.occurrences]
    assert statuses == [
        [STATUS_OK],
        [OUTSIDE_CONSTRAINT],
        [NEGATIVE_DURATION],
        [STATUS_OK],
        [EVENT_NEVER_CAME],
    ]
    assert problem_run.occurrences[1].outside == Q_(60, "s")


def test_the_summary_counts_each_status(problem_run):
    assert problem_run.activity_summary == (
        "Occurrences: 5 in 1 repeat. Negative duration: 1. Outside constraint: 1. "
        "Event never came: 1. Cut at end: 0. Slew starts early: 0."
    )


def test_the_activity_table_has_a_row_per_occurrence(run):
    table = run.activity_table
    assert len(table) == len(run.occurrences)
    assert list(table.columns) == [
        "repeat",
        "activity",
        "start [UTC]",
        "end [UTC]",
        "duration [min]",
        "trigger",
        "attitude",
        "slew [s]",
        "mode",
        "constraint",
        "outside [s]",
        "status",
    ]
    assert table.loc[0, "start [UTC]"] == "2026-10-01T00:00:00.000"


def test_an_sso_orbit_is_built_at_the_start(data_dir):
    text = (
        (data_dir / "scenario.yaml")
        .read_text()
        .replace("tle_file: sso_510km.tle", 'sso: {altitude: 510 km, ltan: "13:30"}')
    )
    scenario = Scenario.from_yaml_text(text, base_dir=data_dir)
    tle = scenario_tle(scenario)
    assert tle.epoch.utc.isot == "2026-10-01T00:00:00.000"
    assert tle.name == "SSO 510 km, LTAN 13.5 h"
