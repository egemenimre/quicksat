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

The Activity Designer runs the list once, or an empty list. One pass of the
fixture's list ends partway through its three orbits, so the rest is unplanned.
"""

import numpy as np
import portion as P
import pytest
from astropy.tests.helper import assert_quantity_allclose
from astropy.time import Time

from quicksat import Q_, u
from quicksat.orbit.geometry import elevations, geodetic
from quicksat.orbit.omm import write_omm_file
from quicksat.orbit.tle import Tle, read_tle_file
from quicksat.scenario.activities import Activity
from quicksat.scenario.attitude import attitude_names, body_rotations
from quicksat.scenario.attitude_files import attitude_table
from quicksat.scenario.config import Scenario
from quicksat.scenario.events import (
    CUT_AT_END,
    EVENT_NEVER_CAME,
    NEGATIVE_DURATION,
    OUTSIDE_CONSTRAINT,
    STATUS_OK,
    find_events,
    next_event,
    resolve_activities,
)
from quicksat.scenario.names import UNPLANNED
from quicksat.scenario.run import run_length, run_scenario
from quicksat.scenario.sources import scenario_orbit
from quicksat.scenario.tables import activity_table
from quicksat.scenario.viewer import scenario_data
from quicksat.utils.intervals import labels_at, round_time

from .conftest import SLOW, both

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


def resolve(*fields, repeat=True):
    """
    Resolve a list of activities on the made-up run, each given as its fields
    after the title, with one mode for both the payload and the platform. Each
    takes its number as its title. Without `repeat`, the list runs once.
    """
    activities = [
        Activity.from_fields(
            [f"activity {number}", *activity[:2], both(activity[2]), *activity[3:]]
        )
        for number, activity in enumerate(fields, start=1)
    ]

    def time_above(latitude):
        return ABOVE.get(float(latitude.to_value(u.deg)), P.empty())

    events = find_events(activities, RUN, ILLUMINATION, time_above)
    return resolve_activities(activities, RUN, events, ILLUMINATION, repeat)


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


@pytest.mark.parametrize(
    ("length", "fails"), [("1200.5 s", False), ("1201 s", False), ("1201.5 s", True)]
)
def test_a_miss_of_up_to_a_second_counts_as_numerical(length, fails):
    # sunlit until the eclipse at 20 min, so 0.5 s, 1 s or 1.5 s outside
    first = resolve([length, "nadir", "a", "sunlit"], ["30 min", "nadir", "b"])[0]
    assert first.outside is not None
    assert first.outside.to_value(u.s) == pytest.approx(float(length[:-2]) - 1200)
    assert first.failed is fails
    assert first.statuses == ([OUTSIDE_CONSTRAINT] if fails else [STATUS_OK])


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


def test_one_pass_stops_after_its_last_activity():
    occurrences = resolve(
        ["30 min", "nadir", "a"], ["15 min", "nadir", "b"], repeat=False
    )
    assert spans(occurrences) == [(0, 30), (30, 45)]
    assert all(o.statuses == [STATUS_OK] for o in occurrences)


def test_one_pass_longer_than_the_run_is_cut_at_its_end():
    occurrences = resolve(
        ["60 min", "nadir", "a"], ["60 min", "nadir", "b"], repeat=False
    )
    assert spans(occurrences) == [(0, 60), (60, 100)]
    assert occurrences[-1].statuses == [CUT_AT_END]


def test_one_pass_that_never_moves_on_is_not_refused():
    # the run stops after one pass, so it cannot go on for ever
    occurrences = resolve(["eclipse entry - 90 min", "nadir", "a"], repeat=False)
    assert [o.statuses for o in occurrences] == [[NEGATIVE_DURATION]]


@pytest.mark.parametrize("repeat", [True, False])
def test_an_empty_list_gives_no_occurrences(repeat):
    assert resolve(repeat=repeat) == []


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
        Activity.from_fields(["a", trigger, "nadir", both("a")])
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
        run_length(run.scenario, run.orbit), 3 * run.orbit.period, rtol=1e-12
    )


def test_a_step_as_long_as_the_run_is_refused(data_dir):
    text = (data_dir / "scenario.yaml").read_text().replace("3 orbits", "0.001 orbits")
    scenario = Scenario.from_yaml_text(text, base_dir=data_dir)
    with pytest.raises(ValueError, match="step must be shorter than the run"):
        run_length(scenario, scenario_orbit(scenario))


def test_the_grid_ends_exactly_at_the_end_of_the_run(run):
    offsets = (run.times - run.times[0]).to_value(u.s)
    assert np.allclose(np.diff(offsets)[:-1], 10.0)
    assert run.times[-1] == run.interval.upper
    assert offsets[-1] == pytest.approx(3 * run.orbit.period.to_value(u.s), abs=1e-3)


def test_the_gantt_rows_cover_the_run(run):
    for row in (run.illumination, run.attitude, *run.mode.values()):
        assert row.domain() == run.interval
    assert list(run.mode) == ["payload", "platform"]
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
        "activities:\n  - [to the umbra, umbra entry, nadir, {payload_mode: idle, platform_mode: idle}]\n"
        "  - [umbra, umbra exit, nadir, {payload_mode: idle, platform_mode: idle}]\n"
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
        latitude, _ = geodetic(run.orbit.states(times, with_velocity=False))
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
    period = run.orbit.period.to_value(u.s)
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


def test_the_report_lists_only_the_occurrences_with_a_problem(problem_run):
    summary, header, *rows = problem_run.report.splitlines()
    assert summary == problem_run.activity_summary
    assert header.split()[:3] == ["repeat", "activity", "title"]
    statuses = [OUTSIDE_CONSTRAINT, NEGATIVE_DURATION, EVENT_NEVER_CAME]
    assert len(rows) == len(statuses)
    for row, status in zip(rows, statuses, strict=True):
        assert row.endswith(status)


def test_the_activity_table_has_a_row_per_occurrence(run):
    table = run.activity_table
    assert len(table) == len(run.occurrences)
    assert list(table.columns) == [
        "repeat",
        "activity",
        "title",
        "start [UTC]",
        "end [UTC]",
        "duration [min]",
        "trigger",
        "attitude",
        "slew [s]",
        "payload mode",
        "platform mode",
        "constraint",
        "outside [s]",
        "status",
    ]
    assert table.loc[0, "start [UTC]"] == "2026-10-01T00:00:00.000"
    assert table.loc[0, "title"] == "to the node"


def test_an_sso_orbit_is_built_at_the_start(data_dir):
    text = (
        (data_dir / "scenario.yaml")
        .read_text()
        .replace("tle_file: sso_510km.tle", 'sso: {altitude: 510 km, ltan: "13:30"}')
    )
    scenario = Scenario.from_yaml_text(text, base_dir=data_dir)
    tle = scenario_orbit(scenario)
    assert tle.epoch.utc.isot == "2026-10-01T00:00:00.000"
    assert tle.name == "SSO 510 km, LTAN 13.5 h"


def test_an_ltdn_gives_the_orbit_of_the_ltan_12_h_away(data_dir):
    def tle(node):
        text = (
            (data_dir / "scenario.yaml")
            .read_text()
            .replace("tle_file: sso_510km.tle", f"sso: {{altitude: 510 km, {node}}}")
        )
        return scenario_orbit(Scenario.from_yaml_text(text, base_dir=data_dir))

    ascending = tle('ltan: "22:30"')
    descending = tle('ltdn: "10:30"')
    assert descending.name == "SSO 510 km, LTDN 10.5 h"
    assert descending.lines[1:] == ascending.lines[1:]


def test_an_omm_file_gives_the_tle_it_was_written_from(data_dir, tmp_path):
    # the run takes its orbit from scenario_orbit, so the same TLE gives the same run
    tle = read_tle_file(data_dir / "sso_510km.tle")
    write_omm_file(tmp_path / "leo.omm", tle)
    text = (data_dir / "scenario.yaml").read_text()
    text = text.replace("tle_file: sso_510km.tle", "omm_file: leo.omm")
    scenario = Scenario.from_yaml_text(text, base_dir=tmp_path)
    assert scenario.orbit.omm_file == tmp_path / "leo.omm"
    orbit = scenario_orbit(scenario)
    assert isinstance(orbit, Tle)
    assert orbit.lines == tle.lines


# ---------------------------------------------------------------- Ground targets

PASSES = """
orbit: {tle_file: sso_510km.tle}
start: 2026-10-01T00:00:00
duration: 3 orbits
gnd_targets:
  Svalbard: {latitude: 78.229 deg, longitude: 15.408 deg, altitude: 500 m}
  Overhead: {latitude: 0 deg, longitude: 0 deg, min_elevation: 89.9 deg}
attitudes:
  nadir: {point: [+z, nadir], constrain: [-y, orbit normal]}
  track Svalbard: {point: [+z, Svalbard], constrain: [-y, orbit normal]}
activities:
  - [wait for Svalbard, Svalbard rise, nadir, {payload_mode: idle, platform_mode: idle}]
  - [downlink Svalbard, Svalbard set, track Svalbard, {payload_mode: downlink, platform_mode: downlink}]
"""
"""Three orbits that wait for each Svalbard pass, and track it."""


@pytest.fixture(scope="module")
def pass_run(data_dir):
    """Three orbits of `PASSES`."""
    return run_scenario(Scenario.from_yaml_text(PASSES, data_dir))


def test_a_pass_runs_from_the_rise_to_the_set_at_the_minimum_elevation(pass_run):
    target = pass_run.scenario.gnd_targets["Svalbard"]
    place = (target.latitude, target.longitude, target.altitude)
    passes = [
        o
        for o in pass_run.occurrences
        if o.activity.mode.payload == "downlink" and not o.cut_at_end
    ]
    assert len(passes) >= 2
    for occurrence in passes:
        span = (occurrence.end - occurrence.start).to_value(u.s)
        times = occurrence.start + Q_(np.linspace(0, span, 50), "s")
        seen = elevations(pass_run.orbit.states(times, with_velocity=False), *place)
        # the ends sit on 5 deg, to the 1 ms grid, and the pass stays above it
        assert seen[[0, -1]] == pytest.approx([5, 5], abs=0.01)
        assert seen[1:-1].min() > 5
    assert all(o.statuses == [STATUS_OK] for o in pass_run.occurrences[:-1])


def test_a_target_that_never_rises_never_ends_the_activity(data_dir):
    text = PASSES.replace("Svalbard rise, nadir,", "Overhead rise, nadir,")
    run = run_scenario(Scenario.from_yaml_text(text, data_dir))
    assert len(run.occurrences) == 1
    assert run.occurrences[0].statuses == [EVENT_NEVER_CAME]


def test_the_viewer_data_gives_each_ground_target_and_its_passes(pass_run):
    data = scenario_data(pass_run)
    svalbard, overhead = data["targets"]
    assert svalbard["name"] == "Svalbard"
    assert svalbard["kind"] == "ground"
    assert (svalbard["latitude_deg"], svalbard["longitude_deg"]) == (78.229, 15.408)
    assert (svalbard["altitude_km"], svalbard["min_elevation_deg"]) == (0.5, 5.0)
    start = pass_run.times[0]
    assert [(p["start_s"], p["end_s"]) for p in svalbard["passes"]] == [
        (
            round(float((piece.lower - start).to_value(u.s)), 3),
            round(float((piece.upper - start).to_value(u.s)), 3),
        )
        for piece in pass_run.in_view["Svalbard"]
    ]
    assert all(p["closest_km"] is None for p in svalbard["passes"])
    assert overhead["passes"] == []
    assert data["target_files"] == []
    assert data["pointing"]["attitudes"] == {"track Svalbard": ["Svalbard"]}


# ---------------------------------------------------------------- One pass


def test_one_pass_leaves_the_rest_of_the_run_unplanned(once_run):
    assert [o.number for o in once_run.occurrences] == list(range(1, 9))
    assert {o.repeat for o in once_run.occurrences} == {1}
    end = once_run.occurrences[-1].end
    assert end < once_run.interval.upper
    assert once_run.unplanned == P.closedopen(end, once_run.interval.upper)
    # the rows still cover the run, the unplanned time included
    for row in (once_run.illumination, once_run.attitude, *once_run.mode.values()):
        assert row.domain() == once_run.interval
    for row in once_run.mode.values():
        assert row.find(UNPLANNED) == once_run.unplanned


def test_one_pass_takes_as_long_with_repeats_or_without(once_run, run):
    last = once_run.occurrences[-1]
    assert once_run.pass_length == (last.end - once_run.interval.lower).to(u.s)
    # the slews and the wings do not move the activities, so the first pass of
    # the full run ends at the same time
    assert run.pass_length == once_run.pass_length
    assert run.repeat
    assert not once_run.repeat


def test_a_pass_longer_than_the_run_has_no_length(data_dir):
    text = (data_dir / "scenario.yaml").read_text().replace("3 orbits", "0.5 orbits")
    run = run_scenario(Scenario.from_yaml_text(text, data_dir))
    assert run.pass_length is None


def test_a_full_run_has_no_unplanned_time(run):
    assert run.unplanned.empty
    assert UNPLANNED not in run.attitude.values()
    run.check_planned("the report")


def test_the_body_has_no_orientation_in_the_unplanned_time(once_run):
    after = once_run.times >= once_run.unplanned.lower
    names = attitude_names(once_run)
    assert set(names[after]) == {UNPLANNED}
    assert UNPLANNED not in set(names[~after])
    rotations = body_rotations(once_run)
    assert np.isnan(rotations[after]).all()
    assert np.isfinite(rotations[~after]).all()


def test_one_pass_warns_as_the_same_occurrences_of_a_full_run(
    once_run, once_text, data_dir
):
    full = run_scenario(Scenario.from_yaml_text(once_text, data_dir))
    first = [e.text for e in full.rate_excesses if e.occurrence.repeat == 1]
    assert first
    assert [e.text for e in once_run.rate_excesses] == first
    assert once_run.warnings == first


def test_nadir_is_fixed_in_body_axes_in_the_nadir_attitude(slew_run):
    # nadir points +z at the centre of the Earth, so the slews and the other
    # attitudes are the only times it moves
    names = attitude_names(slew_run)
    nadir = names == "nadir"
    assert nadir.any() and not nadir.all()
    np.testing.assert_allclose(slew_run.nadir_body[nadir] - [0, 0, 1], 0, atol=1e-9)
    np.testing.assert_allclose(np.linalg.norm(slew_run.nadir_body, axis=1), 1)
    assert slew_run.nadir_body[~nadir, 2].min() < 0.99


def test_the_sun_zenith_cosine_is_negative_in_the_umbra(slew_run):
    umbra = labels_at(slew_run.illumination, slew_run.times) == "umbra"
    assert umbra.any()
    assert slew_run.sun_zenith_cosine[umbra].max() < 0
    assert slew_run.sun_zenith_cosine.max() > 0


@pytest.mark.parametrize(
    "work_out",
    [
        lambda run: run.sun_body,
        lambda run: run.nadir_body,
        lambda run: run.report,
        lambda run: run.articulations,
        attitude_table,
    ],
    ids=[
        "sun in body axes",
        "nadir in body axes",
        "report",
        "articulations",
        "attitude file",
    ],
)
def test_what_needs_the_whole_run_planned_refuses_one_pass(once_run, work_out):
    with pytest.raises(
        ValueError, match="no activity plans the run from .* to its end"
    ):
        work_out(once_run)


@pytest.mark.parametrize("repeat", [True, False])
def test_an_empty_list_leaves_the_whole_run_unplanned(data_dir, repeat):
    text = (data_dir / "scenario.yaml").read_text().split("activities:")[0]
    text += "activities: []\n" + SLOW
    run = run_scenario(Scenario.from_yaml_text(text, data_dir, designer=True), repeat)
    assert run.occurrences == []
    assert run.slews == []
    assert run.unplanned == run.interval
    assert set(run.attitude.values()) == {UNPLANNED}
    for row in run.mode.values():
        assert set(row.values()) == {UNPLANNED}
    assert np.isnan(body_rotations(run)).all()
    assert run.rate_excesses == []
    assert run.warnings == []
    assert run.activity_summary.startswith("Occurrences: 0 in 0 repeats.")
    assert run.activity_table.empty
    assert run.pass_length == Q_(0, "s")
