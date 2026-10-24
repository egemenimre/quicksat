# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Running a scenario: the orbit, the eclipses and the repeated activities.

`run_scenario` evaluates the orbit on the time grid and finds the umbra and the
penumbra, and the latitude crossings that the triggers name. It finds when each
target is in view: a ground target above its minimum elevation, and a satellite
target with the line between the two above its minimum clearance. It repeats the
list of activities until the duration ends and checks each constraint. All the
results come back in one `ScenarioRun`.

The Activity Designer can run the list once, with no repeats, or run an empty
list. The time after the last activity is then unplanned. The attitude and both
mode rows give it as `unplanned`, and the body has no orientation then. Whatever
needs the whole run planned refuses such a run.

Each orbit is checked against the run before it is used. An element set more
than 7 days from either end of the run gets a warning, and so does a trajectory
whose ends come close to the run's. A trajectory that does not cover the run
stops it. The warnings come back in `ScenarioRun.warnings`, as well as through
Python's warnings.

Every time interval is closed at its start and open at its end. Every bound goes
through `round_time`. So the pieces of a run fit together with no gaps and no
overlaps.

"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import portion as P
from astropy.coordinates import CartesianRepresentation, SkyCoord
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.geometry import (
    beta_angle,
    elevations,
    geodetic,
    light_fraction,
    line_of_sight_clear,
    shadow_cones,
    shadow_intervals,
    sun_positions,
)
from quicksat.orbit.omm import read_omm_file, read_omm_sets
from quicksat.orbit.sso import sso_tle
from quicksat.orbit.tle import (
    Tle,
    pick_element_set,
    read_tle_file,
    read_tle_sets,
    warn_if_far_from_epoch,
)
from quicksat.orbit.trajectory import Trajectory
from quicksat.orbit.trajectory_files import read_trajectory_file
from quicksat.scenario.articulation import articulation_angles
from quicksat.scenario.attitude import SlewWindow, body_rotations, plan_slews
from quicksat.scenario.config import (
    GROUPS,
    LATITUDE_CROSSING,
    PAYLOAD,
    PLATFORM,
    RISE,
    SET,
    SLEW,
    THIS_ACTIVITY,
    UNPLANNED,
    Activity,
    OrbitCount,
    Scenario,
    Trigger,
)
from quicksat.scenario.grid import RunGrid
from quicksat.scenario.rates import RateExcess, rate_excesses
from quicksat.utils.intervals import (
    TimeArray,
    duration,
    intervals_where,
    next_start,
    round_time,
)

OrbitSource = Tle | Trajectory
"""Where a run's states come from: an element set for SGP4, or a trajectory.
Each gives a `name`, a `period` for a duration in orbits, and `states(times)` in
GCRS."""

Illumination = dict[str, P.Interval]
"""The illumination of a run, by the words of the constraints: `sunlit`,
`penumbra`, `umbra`, and `eclipse` for either of the last two."""

Events = dict[tuple, tuple[P.Interval, ...]]
"""The events of a run, by `Trigger.event_key`. Each event is the start of a
piece of one of the intervals."""

OUTSIDE_CONSTRAINT = "outside constraint"
"""Status: the activity spends more than `CONSTRAINT_TOLERANCE` outside its
constraint."""

EVENT_NEVER_CAME = "event never came"
"""Status: the event that ends the activity never happens in the run, such as an
eclipse entry in a season with no eclipses. The activity runs to the end of the
run."""

CUT_AT_END = "cut at end"
"""Status: the activity would run past the end of the run, and is cut there. This
includes an event trigger whose next event comes after the end of the run."""

NEGATIVE_DURATION = "negative duration"
"""Status: a negative offset takes the end of the activity back to its start, or
before it. The activity then takes no time, and the next one starts where this one
started. This is a fault of the trigger, where `outside constraint` is a fault of
the constraint."""

SLEW_STARTS_EARLY = "slew starts early"
"""Status: the slew into the activity starts before the activity before it does,
because that activity is shorter than the slew. It can also run on into the
activity, if the run starts too late for it."""

STATUS_OK = "ok"
"""Status: none of the above."""

CONSTRAINT_TOLERANCE = Q_(1, "s")
"""Time outside a constraint that still counts as none. It covers numerical
effects only. Event times sit on the 1 ms grid and are found to it, so such
effects are a few milliseconds. A longer miss fails, with no warning step."""


@dataclass(frozen=True)
class Occurrence:
    """
    One activity, as it happens in the run.

    The list of activities is repeated until the duration ends, so each activity
    in the list happens once per repeat.

    Parameters
    ----------
    repeat : int
        Which repeat of the list this is, counted from 1
    number : int
        The number of the activity in the list, counted from 1
    activity : Activity
        The activity as written
    start, end : Time
        Start and end, on the 1 ms grid. A negative offset can take the end back
        to the start, or before it.
    outside : Quantity or None
        Total time spent outside the constraint, or None if there is no constraint
    event_never_came : bool
        True if the event that ends the activity never happens in the run
    cut_at_end : bool
        True if the activity would have ended after the end of the run. That
        includes an event that happens in the run, but not again before its end.
    slew : Quantity, optional
        The time of the slew into the activity, settling included. None if the
        attitude does not change, or the scenario has no slews.
    slew_starts_early : bool, optional
        True if the slew into the activity starts before the activity before it
    """

    repeat: int
    number: int
    activity: Activity
    start: TimeArray
    end: TimeArray
    outside: Quantity | None
    event_never_came: bool
    cut_at_end: bool
    slew: Quantity | None = None
    slew_starts_early: bool = False

    @property
    def interval(self) -> P.Interval:
        """
        The occurrence as a time interval, closed at its start and open at its end.

        Returns
        -------
        interval : portion.Interval
            Empty if the activity ends at or before its start
        """
        return P.closedopen(self.start, self.end)

    @property
    def negative_duration(self) -> bool:
        """
        Whether a negative offset takes the end back to the start, or before it.

        Returns
        -------
        negative_duration : bool
            True for a duration of zero too
        """
        return bool(self.end <= self.start)

    @property
    def failed(self) -> bool:
        """
        Whether the activity spends more than `CONSTRAINT_TOLERANCE` outside its
        constraint.

        Returns
        -------
        failed : bool
            False if there is no constraint
        """
        return self.outside is not None and bool(self.outside > CONSTRAINT_TOLERANCE)

    @property
    def statuses(self) -> list[str]:
        """
        The statuses of the occurrence. It can have more than one.

        Returns
        -------
        statuses : list of str
            `negative duration`, `outside constraint`, `event never came`,
            `cut at end` and `slew starts early`, as far as they apply, or `ok` if
            none does
        """
        statuses = []
        if self.negative_duration:
            statuses.append(NEGATIVE_DURATION)
        if self.failed:
            statuses.append(OUTSIDE_CONSTRAINT)
        if self.event_never_came:
            statuses.append(EVENT_NEVER_CAME)
        if self.cut_at_end:
            statuses.append(CUT_AT_END)
        if self.slew_starts_early:
            statuses.append(SLEW_STARTS_EARLY)
        return statuses or [STATUS_OK]


def scenario_orbit(scenario: Scenario) -> OrbitSource:
    """
    Where the scenario's states come from.

    An element set is read from the TLE file or the OMM file, or built for the
    sun-synchronous orbit, with its epoch at the start of the run. A trajectory
    is read from the trajectory file.

    Parameters
    ----------
    scenario : Scenario
        The scenario

    Returns
    -------
    orbit : Tle or Trajectory
        The element set or the trajectory
    """
    orbit = scenario.orbit
    if orbit.sso is not None:
        sso = orbit.sso
        name = f"SSO {sso.altitude:g}, {sso.node_label}"
        return sso_tle(
            round_time(scenario.start), sso.altitude, sso.ascending_node_time, name=name
        )
    if orbit.trajectory_file is not None:
        return read_trajectory_file(orbit.trajectory_file)
    if orbit.omm_file is not None:
        return read_omm_file(orbit.omm_file)
    assert orbit.tle_file is not None  # the orbit has exactly one of the four
    return read_tle_file(orbit.tle_file)


def target_orbits(scenario: Scenario) -> dict[str, OrbitSource]:
    """
    Where each satellite target's states come from, read from its file.

    A TLE or OMM file gives the element set that the target's `object` names.
    Without `object`, a file of one element set gives that one, and a file of
    several gives the one named as the target. A file that several targets share
    is read once.

    Parameters
    ----------
    scenario : Scenario
        The scenario

    Returns
    -------
    orbits : dict of str to Tle or Trajectory
        Each satellite target's element set or trajectory, by its name

    Raises
    ------
    FileNotFoundError
        If a target's file does not exist
    ValueError
        If a target's file cannot be read, or does not hold the element set asked
        for. The message names the target.
    """
    read: dict[Path, list[Tle]] = {}
    orbits: dict[str, OrbitSource] = {}
    for name, target in scenario.sat_targets.items():
        try:
            if target.trajectory_file is not None:
                orbits[name] = read_trajectory_file(target.trajectory_file)
                continue
            path = target.file
            if path not in read:
                reader = read_tle_sets if target.tle_file is not None else read_omm_sets
                read[path] = reader(path)
            wanted = target.satellite
            if wanted is None and len(read[path]) > 1:
                wanted = name
            orbits[name] = pick_element_set(read[path], wanted, path)
        except (OSError, ValueError) as error:
            raise type(error)(f"satellite target '{name}': {error}") from error
    return orbits


def orbit_warnings(
    scenario: Scenario,
    orbit: OrbitSource,
    sat_orbits: dict[str, OrbitSource],
    start: TimeArray,
    end: TimeArray,
) -> list[str]:
    """
    Check each orbit against the run: an element set's epoch, and a trajectory's
    span.

    An element set gets a warning when either end of the run is more than 7
    days from its epoch. The sun-synchronous orbit is left out: quicksat builds
    its element set, with the epoch at the start, so it defines the orbit rather
    than tracking one. A trajectory must cover the run, and gets a warning when
    the run comes close to one of its ends.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    orbit : Tle or Trajectory
        Where the scenario's own states come from
    sat_orbits : dict of str to Tle or Trajectory
        The satellite targets' orbits, by name
    start, end : Time
        The start and the end of the run

    Returns
    -------
    warnings : list of str
        The text of each warning, which Python's warnings also give

    Raises
    ------
    ValueError
        If a trajectory does not cover the run, or crosses a gap in it
    """
    labels: dict[str, OrbitSource] = {}
    if isinstance(orbit, Trajectory):
        labels["the trajectory"] = orbit
    elif scenario.orbit.sso is None:
        labels["the orbit's element set"] = orbit
    for name, source in sat_orbits.items():
        if isinstance(source, Trajectory):
            labels[f"the trajectory of satellite target '{name}'"] = source
        else:
            labels[f"satellite target '{name}'"] = source
    found = []
    for label, source in labels.items():
        if isinstance(source, Trajectory):
            text = source.check_covers(start, end, label)
        else:
            text = warn_if_far_from_epoch(source, start, end, label)
        if text is not None:
            found.append(text)
    return found


def run_length(scenario: Scenario, orbit: OrbitSource) -> Quantity:
    """
    The length of the run, as a time.

    A duration given as a time is used as it is. A number of orbits is multiplied
    by the orbit's period: the nodal period of an element set, or the period
    measured from a trajectory.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    orbit : Tle or Trajectory
        Where the scenario's states come from

    Returns
    -------
    length : Quantity
        The length of the run, in seconds

    Raises
    ------
    ValueError
        If the step is not shorter than the run, or if the duration is in orbits
        and the trajectory is too short to measure one
    """
    duration = scenario.duration
    if isinstance(duration, OrbitCount):
        if isinstance(orbit, Trajectory) and not orbit.period_measured:
            raise ValueError(
                "the trajectory covers less than one orbit, so it has no measured "
                "period. Give the duration as a time, such as '5 h'."
            )
        length = Q_(duration.count * orbit.period.to(u.s).value, "s")
    else:
        length = duration.to(u.s)
    if scenario.step >= length:
        raise ValueError(
            f"step must be shorter than the run, got '{scenario.step}' and "
            f"'{duration}', which is {length.to(u.min):.2f}"
        )
    return length


def next_event(intervals: tuple[P.Interval, ...], after: TimeArray) -> TimeArray | None:
    """
    The first event strictly after a given time.

    Each event is the start of a piece of one of the intervals. A latitude
    crossing in either direction has two intervals: the time above the latitude,
    whose starts are the northward crossings, and the time below it.

    Parameters
    ----------
    intervals : tuple of portion.Interval
        The intervals whose starts are the events
    after : Time
        A single time

    Returns
    -------
    event : Time or None
        The first event after `after`, or None if there is none
    """
    starts = [next_start(piece, after) for piece in intervals]
    found = [start for start in starts if start is not None]
    return min(found) if found else None


def find_events(
    activities: list[Activity],
    interval: P.Interval,
    illumination: Illumination,
    time_above: Callable[[Quantity], P.Interval],
    time_visible: Callable[[str], P.Interval] | None = None,
) -> Events:
    """
    The events that the activities' triggers name, as the intervals they start.

    An eclipse entry is the start of an eclipse, and an eclipse exit the start of
    a sunlit piece. An umbra entry is the start of the umbra, and an umbra exit
    the start of the time outside it. A northward crossing of a latitude is the
    start of the time above it, and a southward crossing is the start of the time
    below it. The time above each latitude is found once, whichever directions the
    triggers name. A target's rise is the start of the time it is in view, and
    its set the start of the time it is not.

    Parameters
    ----------
    activities : list of Activity
        One repeat of the list
    interval : portion.Interval
        The run, closed at its start and open at its end
    illumination : dict
        The intervals of `sunlit`, `penumbra`, `umbra` and `eclipse`
    time_above : callable
        Gives the time at or above a geodetic latitude, as intervals over the run
    time_visible : callable, optional
        Gives the time a target, by name, is in view, as intervals over the run.
        Needed only for the `rise` and `set` triggers.

    Returns
    -------
    events : dict
        For the `event_key` of each event trigger, the intervals whose starts are
        its events
    """
    shadow_edges = {
        "eclipse entry": illumination["eclipse"],
        "eclipse exit": illumination["sunlit"],
        "umbra entry": illumination["umbra"],
        "umbra exit": interval - illumination["umbra"],
    }
    events: Events = {}
    above: dict[float, P.Interval] = {}
    visible: dict[str, P.Interval] = {}
    for activity in activities:
        trigger = activity.trigger
        key = trigger.event_key
        if key is None or key in events:
            continue
        if trigger.event in shadow_edges:
            events[key] = (shadow_edges[trigger.event],)
        elif trigger.event in (RISE, SET):
            if time_visible is None:
                raise ValueError(f"trigger '{trigger.text}' needs time_visible")
            target = cast(str, trigger.target)  # a rise or a set has one
            if target not in visible:
                visible[target] = time_visible(target)
            seen = visible[target]
            events[key] = (seen,) if trigger.event == RISE else (interval - seen,)
        else:
            assert trigger.event == LATITUDE_CROSSING
            assert trigger.latitude is not None  # a latitude crossing has one
            degrees = key[1]
            if degrees not in above:
                above[degrees] = time_above(trigger.latitude)
            northward, southward = above[degrees], interval - above[degrees]
            events[key] = {
                "ascending": (northward,),
                "descending": (southward,),
                None: (northward, southward),
            }[trigger.direction]
    return events


def _trigger_end(
    trigger: Trigger, start: TimeArray, events: Events
) -> TimeArray | None:
    """
    When a trigger ends an activity that starts at a given time.

    Parameters
    ----------
    trigger : Trigger
        The end trigger of the activity
    start : Time
        When the activity starts, on the 1 ms grid
    events : dict
        The events of the run, from `find_events`

    Returns
    -------
    end : Time or None
        A duration trigger ends the activity that long after `start`. An event
        trigger ends it at the first such event strictly after `start`, moved by
        the offset if there is one. If there is no such event, the result is None.
    """
    if trigger.duration is not None:
        return round_time(start + trigger.duration)
    key = trigger.event_key
    assert key is not None  # a trigger has a duration or an event
    event = next_event(events[key], start)
    if event is None or trigger.offset is None:
        return event
    return round_time(event + trigger.offset)


def resolve_activities(
    activities: list[Activity],
    interval: P.Interval,
    events: Events,
    allowed: dict[str, P.Interval],
    repeat: bool = True,
) -> list[Occurrence]:
    """
    Repeat the list of activities until the run ends, and check the constraints.

    The first activity starts at the start of the run. Each later one starts
    where the one before it ends. A duration trigger ends the activity that long
    after its start. An event trigger ends it at the first such event strictly
    after its start, moved by its offset. An activity that would end after the end
    of the run is cut there. So is one whose event happens in the run, but not
    again before the end. If the event never happens in the run at all, the
    activity runs to the end and is flagged that its event never came.

    A negative offset can take an activity's end back to its start, or before it.
    The activity is then flagged, and takes no time. The next activity starts
    where it started.

    A constraint holds when the activity spends no more than `CONSTRAINT_TOLERANCE`
    outside the intervals that the constraint allows.

    Without repeats, the list runs once. It stops after its last activity, or at
    the end of the run if that comes first. The time after it has no occurrence.

    Parameters
    ----------
    activities : list of Activity
        One repeat of the list. It may be empty, which gives no occurrences.
    interval : portion.Interval
        The run, closed at its start and open at its end
    events : dict
        The events of the run, from `find_events`
    allowed : dict
        The intervals that each constraint allows, by the name of the constraint
    repeat : bool, optional
        Whether to repeat the list until the run ends, as by default, or run it
        once

    Returns
    -------
    occurrences : list of Occurrence
        Every occurrence, in order, from the start of the run to its end, or to
        the end of the single pass

    Raises
    ------
    ValueError
        If the list repeats and no activity in it ends after it starts. The run
        would then never move on.
    """
    if not activities:
        return []
    run_end: TimeArray = interval.upper
    occurrences = []
    start: TimeArray = interval.lower
    repeat_start = start
    index, repeat_number = 0, 1
    while start < run_end:
        activity = activities[index]
        trigger = activity.trigger
        end = _trigger_end(trigger, start, events)
        if end is None:
            # an event trigger with no such event after the start
            key = trigger.event_key
            assert key is not None  # only an event can be missing
            never_came = next_event(events[key], interval.lower) is None
            cut = not never_came
            end = run_end
        else:
            never_came = False
            cut = bool(end > run_end)
            if cut:
                end = run_end

        outside = None
        if activity.constraint is not None:
            outside = duration(P.closedopen(start, end) - allowed[activity.constraint])
        occurrences.append(
            Occurrence(
                repeat_number, index + 1, activity, start, end, outside, never_came, cut
            )
        )

        # an activity that ends before it starts takes no time
        start = max(start, end)
        index += 1
        if index == len(activities):
            if not repeat:
                break
            if start == repeat_start:
                raise ValueError(
                    "No activity in the list ends after it starts, so the run never "
                    f"moves on from {start.utc.isot}. Every activity has a negative "
                    "offset that takes its end back to its start or before it. "
                    "Shorten the offsets."
                )
            index, repeat_number, repeat_start = 0, repeat_number + 1, start
    return occurrences


def activity_table(occurrences: list[Occurrence]) -> pd.DataFrame:
    """
    Tabulate the occurrences, one row each.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences from `resolve_activities`

    Returns
    -------
    table : pd.DataFrame
        The columns are the repeat and activity numbers, the title, the start and
        end as UTC text, the duration in minutes, the trigger as written, the attitude, the
        time of the slew into it in seconds, the payload's mode and the
        platform's, the constraint, the time
        outside the constraint in seconds, and the status. The duration is
        negative for an activity that ends before it starts. The status is `ok`,
        or any of `negative duration`, `outside constraint`, `event never came`,
        `cut at end` and `slew starts early`, joined by commas. The slew is NaN
        where there is none. The constraint is blank and the time outside is NaN
        where an activity has no constraint.
    """
    rows = []
    for occurrence in occurrences:
        activity = occurrence.activity
        rows.append(
            {
                "repeat": occurrence.repeat,
                "activity": occurrence.number,
                "title": activity.title,
                "start [UTC]": occurrence.start.utc.isot,
                "end [UTC]": occurrence.end.utc.isot,
                "duration [min]": round(
                    float((occurrence.end - occurrence.start).to_value(u.s)), 3
                )
                / 60,
                "trigger": activity.trigger.text,
                "attitude": activity.attitude,
                "slew [s]": (
                    np.nan if occurrence.slew is None else occurrence.slew.to_value(u.s)
                ),
                "payload mode": activity.mode.payload,
                "platform mode": activity.mode.platform,
                "constraint": activity.constraint or "",
                "outside [s]": (
                    np.nan
                    if occurrence.outside is None
                    else occurrence.outside.to_value(u.s)
                ),
                "status": ", ".join(occurrence.statuses),
            }
        )
    return pd.DataFrame(rows)


def activity_summary(occurrences: list[Occurrence]) -> str:
    """
    One line that sums up the occurrences and how many have a problem.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences from `resolve_activities`

    Returns
    -------
    summary : str
        The number of occurrences and repeats, and how many have a negative
        duration, are outside their constraint, saw an event that never came, were
        cut at the end, or have a slew that starts early
    """
    repeats = occurrences[-1].repeat if occurrences else 0
    early = sum(occurrence.negative_duration for occurrence in occurrences)
    failed = sum(occurrence.failed for occurrence in occurrences)
    never_came = sum(occurrence.event_never_came for occurrence in occurrences)
    cut = sum(occurrence.cut_at_end for occurrence in occurrences)
    slews = sum(occurrence.slew_starts_early for occurrence in occurrences)
    return (
        f"Occurrences: {len(occurrences)} in {repeats} repeat{'' if repeats == 1 else 's'}. "
        f"{NEGATIVE_DURATION.capitalize()}: {early}. "
        f"{OUTSIDE_CONSTRAINT.capitalize()}: {failed}. "
        f"{EVENT_NEVER_CAME.capitalize()}: {never_came}. "
        f"{CUT_AT_END.capitalize()}: {cut}. "
        f"{SLEW_STARTS_EARLY.capitalize()}: {slews}."
    )


def gantt_rows(
    illumination: Illumination,
    occurrences: list[Occurrence],
    slews: list[SlewWindow],
) -> tuple[P.IntervalDict, P.IntervalDict, dict[str, P.IntervalDict]]:
    """
    Build the rows of the Gantt chart: the illumination, the attitude, and the
    payload's and the platform's modes.

    Each row has exactly one value at any time of the run. Touching pieces with
    the same value merge into one. The attitude and mode rows give the time after
    the last occurrence, if any, as `unplanned`.

    Parameters
    ----------
    illumination : dict
        The intervals of `sunlit`, `penumbra` and `umbra`
    occurrences : list of Occurrence
        The occurrences from `resolve_activities`
    slews : list of SlewWindow
        The slews, from `plan_slews`. They take the attitude row's and the
        platform's mode row's time over from the activities. They take the
        payload's too, where the activity after the slew asks for its own mode
        through `payload_mode_in_slew`.

    Returns
    -------
    illumination : portion.IntervalDict
        `sunlit`, `penumbra` and `umbra`
    attitude : portion.IntervalDict
        The attitude names, `slew` while the body turns or settles, and
        `unplanned` after the last occurrence
    mode : dict of str to portion.IntervalDict
        The mode names of the payload and of the platform, by the group's name,
        and `unplanned` after the last occurrence. The platform's mode is `slew`
        while the body turns or settles. By default, the payload's carries on
        through the turn, which takes the end of the activity before it. With
        `payload_mode_in_slew: this_activity`, the payload takes the mode of the
        activity after the slew for the whole turn.
    """
    row = P.IntervalDict()
    for state in ("sunlit", "penumbra", "umbra"):
        row[illumination[state]] = state
    attitude = P.IntervalDict()
    mode = {group: P.IntervalDict() for group in GROUPS}
    for occurrence in occurrences:
        attitude[occurrence.interval] = occurrence.activity.attitude
        for group in GROUPS:
            mode[group][occurrence.interval] = occurrence.activity.mode[group]
    # the illumination covers the whole run, so what is left of it is unplanned
    unplanned = row.domain() - attitude.domain()
    if not unplanned.empty:
        attitude[unplanned] = UNPLANNED
        for group in GROUPS:
            mode[group][unplanned] = UNPLANNED
    for window in slews:
        attitude[window.interval] = SLEW
        mode[PLATFORM][window.interval] = SLEW
        modes = occurrences[window.into].activity.mode
        if modes.payload_mode_in_slew == THIS_ACTIVITY:
            mode[PAYLOAD][window.interval] = modes.payload
    return row, attitude, mode


def _km(state: SkyCoord) -> np.ndarray:
    """A state's positions in km, one row each."""
    cartesian = cast(CartesianRepresentation, state.cartesian)
    return np.atleast_2d(cartesian.xyz.to_value(u.km).T)


def pass_table(run: "ScenarioRun") -> pd.DataFrame:
    """
    Tabulate every target's passes: each time it is in view, one row each.

    A pass under way when the run starts begins at the start, and one under way
    when it ends ends at the end. So it is cut, as the run is.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    table : pd.DataFrame
        The columns are the target, the start and the end of the pass as UTC
        text, its duration in minutes, and, for a satellite target, the closest
        range in km at the grid's times in the pass. The range is NaN for a
        ground target, and for a pass between two grid times. The rows are in
        the order of their starts.
    """
    columns = ["target", "from [UTC]", "to [UTC]", "duration [min]", "closest [km]"]
    here = _km(run.state)
    rows = []
    for name, seen in run.in_view.items():
        ranges = None
        if name in run.sat_states:
            ranges = np.linalg.norm(_km(run.sat_states[name]) - here, axis=1)
        for piece in seen:
            inside = (run.times >= piece.lower) & (run.times <= piece.upper)
            closest = np.nan
            if ranges is not None and inside.any():
                closest = round(float(ranges[inside].min()), 3)
            rows.append(
                {
                    "target": name,
                    "from [UTC]": piece.lower.utc.isot,
                    "to [UTC]": piece.upper.utc.isot,
                    "duration [min]": duration(piece).to_value(u.min),
                    "closest [km]": closest,
                }
            )
    table = pd.DataFrame(rows, columns=columns)
    return table.sort_values(["from [UTC]", "target"], ignore_index=True)


@dataclass(frozen=True)
class ScenarioRun:
    """
    Everything that running a scenario produces.

    Parameters
    ----------
    scenario : Scenario
        The scenario that was run
    orbit : Tle or Trajectory
        Where the states come from: the element set, or the trajectory
    interval : portion.Interval
        The run, closed at its start and open at its end
    times : Time
        The time grid, from the start to the end of the run, in steps. The end is
        included, and the last step is shorter if the step does not divide the
        duration. Every time is on the 1 ms grid.
    state : SkyCoord
        The satellite's position and velocity on the grid, in GCRS
    sun : CartesianRepresentation
        The position of the sun relative to the centre of the Earth on the grid,
        in GCRS, in km
    latitude, longitude : Quantity
        Geodetic latitude and longitude of the ground track on the grid, with the
        longitude from -180 to 180 degrees
    beta : Quantity
        The beta angle on the grid
    eclipses, sunlit : portion.Interval
        The eclipse and sunlit intervals, which together fill the run
    umbra, penumbra : portion.Interval
        The two parts of the eclipses: where the Earth hides the whole sun, and
        where it hides part of it
    light : ndarray
        The fraction of the sun's disk seen at each time of the grid, from 0 to 1
    illumination, attitude : portion.IntervalDict
        Two rows of the Gantt chart
    mode : dict of str to portion.IntervalDict
        The other two: the payload's and the platform's modes, by the group's
        name, `payload` or `platform`
    occurrences : list of Occurrence
        Every activity as it happens in the run. In a run of the list once, or
        of an empty list, they stop before the end: see `unplanned`.
    slews : list of SlewWindow
        Every slew between attitudes, in time order. Empty when the scenario has
        no slews.
    grid : RunGrid
        The orbits, the sun and the Earth's orientation between the grid's
        steps, and the Earth's orientation on the grid
    activity_table : pd.DataFrame
        The occurrences as a table, from `activity_table`
    sat_orbits : dict of str to Tle or Trajectory
        Where each satellite target's states come from, by its name
    sat_states : dict of str to SkyCoord
        Each satellite target's positions on the grid, in GCRS, by its name
    in_view : dict of str to portion.Interval
        When each target is in view, ground and satellite, by its name
    orbit_warnings : list of str
        The warnings on the orbits, from `orbit_warnings`: an element set far
        from the run, or a trajectory whose ends come close to it
    repeat : bool
        Whether the list of activities repeats until the run ends, as it does
        but in the Activity Designer
    """

    scenario: Scenario
    orbit: OrbitSource
    interval: P.Interval
    times: TimeArray
    state: SkyCoord
    sun: CartesianRepresentation
    latitude: Quantity
    longitude: Quantity
    beta: Quantity  # noqa: V107
    eclipses: P.Interval
    sunlit: P.Interval
    umbra: P.Interval
    penumbra: P.Interval
    light: np.ndarray
    illumination: P.IntervalDict
    attitude: P.IntervalDict
    mode: dict[str, P.IntervalDict]
    occurrences: list[Occurrence]
    slews: list[SlewWindow]
    grid: RunGrid
    activity_table: pd.DataFrame
    sat_orbits: dict[str, OrbitSource] = field(default_factory=dict)
    sat_states: dict[str, SkyCoord] = field(default_factory=dict)
    in_view: dict[str, P.Interval] = field(default_factory=dict)
    orbit_warnings: list[str] = field(default_factory=list)
    repeat: bool = True

    @property
    def unplanned(self) -> P.Interval:
        """
        The time after the last activity, which no activity plans.

        Returns
        -------
        unplanned : portion.Interval
            Empty, unless the list ran once and ended before the run, or was
            empty
        """
        return self.attitude.find(UNPLANNED)

    @property
    def pass_length(self) -> Quantity | None:
        """
        How long one pass of the list of activities takes, from the start of the
        run, as the Activity Designer shows it.

        Returns
        -------
        length : Quantity or None
            In seconds. Zero for an empty list. None when the pass does not end
            in the run: the run ends first, or an event that never comes stops
            the list.
        """
        count = len(self.scenario.activities)
        if count == 0:
            return Q_(0.0, "s")
        last = next(
            (o for o in self.occurrences if o.repeat == 1 and o.number == count), None
        )
        if last is None or last.cut_at_end or last.event_never_came:
            return None
        # an activity with a negative duration ends where it starts
        end = max(last.start, last.end)
        return (end - self.interval.lower).to(u.s)

    def check_planned(self, what: str) -> None:
        """
        Refuse to work out something that needs the activities to fill the run.

        Parameters
        ----------
        what : str
            What would be worked out, such as "the report", for the message

        Raises
        ------
        ValueError
            If part of the run is unplanned: see `unplanned`
        """
        if self.unplanned.empty:
            return
        start = cast(TimeArray, self.unplanned.lower)
        raise ValueError(
            f"Cannot work out {what}: no activity plans the run from "
            f"{start.utc.isot} to its end. Run the list with repeats, and with at "
            "least one activity."
        )

    @cached_property
    def articulations(self) -> dict[str, Quantity]:
        """
        The angle of each articulation of the 3D model, from `articulation_angles`.

        Worked out on first use, because it needs the body's orientation at each
        step.

        Returns
        -------
        angles : dict of str to Quantity
            For each articulation, by its name, its angles in degrees on the grid.
            Empty without articulations.
        """
        return articulation_angles(self)

    @cached_property
    def rate_excesses(self) -> list[RateExcess]:
        """
        The occurrences whose attitude turns faster than the slews may.

        Worked out on first use, from `rate_excesses`. Empty without a `slew`
        block.

        Returns
        -------
        excesses : list of RateExcess
            In time order
        """
        return rate_excesses(self)

    @property
    def warnings(self) -> list[str]:
        """
        Warnings for the reader, as text: the orbits' warnings, then each
        occurrence past the slew capacity.

        Returns
        -------
        warnings : list of str
            One sentence or two for each, the occurrences in time order. Empty
            when there are none.
        """
        return self.orbit_warnings + [excess.text for excess in self.rate_excesses]

    @cached_property
    def passes(self) -> pd.DataFrame:
        """
        Every target's passes, from `pass_table`.

        Returns
        -------
        table : pd.DataFrame
            One row for each time a target is in view
        """
        return pass_table(self)

    @cached_property
    def sun_body(self) -> np.ndarray:
        """
        The direction from the satellite to the sun in body axes, on the grid.

        Worked out on first use, from `body_rotations`, so that it follows the
        body through its slews.

        Returns
        -------
        suns : ndarray
            Unit vectors, shape (n, 3), one for each time of the grid

        Raises
        ------
        ValueError
            If part of the run is unplanned, so that the body has no orientation
            then
        """
        self.check_planned("the direction to the sun in body axes")
        cartesian = self.state.cartesian
        assert isinstance(cartesian, CartesianRepresentation)
        to_sun = self.sun.xyz.to_value(u.km).T - cartesian.xyz.to_value(u.km).T
        to_sun /= np.linalg.norm(to_sun, axis=1, keepdims=True)
        # the rotations turn body vectors into GCRS, so their transposes turn back
        return np.einsum("nji,nj->ni", body_rotations(self), to_sun)

    @property
    def activity_summary(self) -> str:
        """
        One line that sums up the occurrences, from `activity_summary`.

        Returns
        -------
        summary : str
        """
        return activity_summary(self.occurrences)

    @property
    def report(self) -> str:
        """
        The run's results as text, as the command line prints them.

        Returns
        -------
        report : str
            The summary line, a table of the occurrences whose status is not
            `ok`, if any, a line for each target with its passes and its time in
            view, and the warnings, one line each

        Raises
        ------
        ValueError
            If part of the run is unplanned
        """
        self.check_planned("the report")
        table = self.activity_table
        problems = table[table["status"] != STATUS_OK]
        lines = [self.activity_summary]
        if not problems.empty:
            columns = ["repeat", "activity", "title", "start [UTC]", "status"]
            lines.append(problems.loc[:, columns].to_string(index=False))
        for name, seen in self.in_view.items():
            count = len(seen) if not seen.empty else 0
            minutes = duration(seen).to_value(u.min)
            lines.append(
                f"Target {name}: {count} pass{'' if count == 1 else 'es'}, "
                f"{minutes:.1f} min in view."
            )
        return "\n".join(lines + self.warnings)


def _time_above(
    times: TimeArray,
    latitude: Quantity,
    positions_at: Callable[[TimeArray], SkyCoord],
    earth_at: Callable[[TimeArray], np.ndarray],
) -> Callable[[Quantity], P.Interval]:
    """
    The latitude finder that `find_events` takes, over a run's grid.

    Parameters
    ----------
    times : Time
        The run's grid
    latitude : Quantity
        The geodetic latitude on the grid
    positions_at : callable
        Gives the satellite's positions for any `Time` array
    earth_at : callable
        Gives the Earth's orientation for any `Time` array, as `earth_rotations`
        does

    Returns
    -------
    time_above : callable
        Gives the time at or above a geodetic latitude
    """

    def time_above(limit: Quantity) -> P.Interval:
        def above_at(at: TimeArray) -> np.ndarray:
            return np.asarray(geodetic(positions_at(at), earth_at)[0] >= limit)

        return intervals_where(times, np.asarray(latitude >= limit), above_at)

    return time_above


def target_visibility(
    scenario: Scenario,
    times: TimeArray,
    state: SkyCoord,
    sat_states: dict[str, SkyCoord],
    grid: RunGrid,
) -> dict[str, P.Interval]:
    """
    When each target is in view, ground and satellite, over a run's grid.

    A ground target is in view while it sees the satellite at or above its
    minimum elevation. A satellite target is in view while the line between the
    two keeps its minimum clearance above the WGS84 ellipsoid. The edges are found
    between the grid steps, to 1 ms.

    Parameters
    ----------
    scenario : Scenario
        The scenario, for its targets
    times : Time
        The run's grid
    state : SkyCoord
        The satellite's state on the grid
    sat_states : dict of str to SkyCoord
        The satellite targets' positions on the grid, by name
    grid : RunGrid
        The orbits and the Earth's orientation between the grid's steps

    Returns
    -------
    in_view : dict of str to portion.Interval
        For each target, by its name, the time it is in view
    """
    found = {}

    def positions_at(at: TimeArray) -> SkyCoord:
        return grid.satellite.states(at, with_velocity=False)

    for name, ground in scenario.gnd_targets.items():
        place = (ground.latitude, ground.longitude, ground.altitude)
        lowest = ground.min_elevation.to_value(u.deg)

        def visible_at(at: TimeArray, place=place, lowest=lowest) -> np.ndarray:
            seen = elevations(positions_at(at), *place, earth_at=grid.earth)
            return seen >= lowest

        flags = elevations(state, *place, earth_at=grid.earth) >= lowest
        found[name] = intervals_where(times, flags, visible_at)
    for name, target in scenario.sat_targets.items():
        orbit, clearance = grid.targets[name], target.min_clearance

        def clear_at(at: TimeArray, orbit=orbit, clearance=clearance) -> np.ndarray:
            other = orbit.states(at, with_velocity=False)
            return line_of_sight_clear(positions_at(at), other, clearance, grid.earth)

        flags = line_of_sight_clear(state, sat_states[name], clearance, grid.earth)
        found[name] = intervals_where(times, flags, clear_at)
    return found


def run_scenario(scenario: Scenario, repeat: bool = True) -> ScenarioRun:  # noqa: V103
    """
    Run a scenario.

    The orbit comes from the TLE file, from a TLE built for the sun-synchronous
    orbit, or from the trajectory file. It is evaluated on the time grid, with
    SGP4 or by interpolation, and so is each satellite target's orbit. The edges
    of the umbra and the penumbra are then located between the grid steps, and
    so are the latitude crossings that the triggers name, and the edges of each
    target's time in view. Between the steps, the orbits, the sun and the
    Earth's orientation come from splines through the grid: see `RunGrid`. The
    activities are then repeated over the run and checked against the eclipses.
    Each orbit is checked against the run first: see `orbit_warnings`.

    Parameters
    ----------
    scenario : Scenario
        The scenario, from `Scenario.from_yaml_file`
    repeat : bool, optional
        Whether to repeat the list of activities until the run ends, as by
        default, or run it once, as the Activity Designer does at first. The
        time after a single pass is unplanned.

    Returns
    -------
    result : ScenarioRun
        The orbit, the eclipses, the activities and the checks

    Raises
    ------
    ValueError
        If no activity in the list ends after it starts, if a satellite target's
        file does not give its orbit, if the run does not lie inside a
        trajectory, or if SGP4 fails for a satellite target. A message about a
        satellite target names it.
    """
    orbit = scenario_orbit(scenario)
    sat_orbits = target_orbits(scenario)
    start = round_time(scenario.start)

    duration_s = run_length(scenario, orbit).to(u.s).value
    step_s = scenario.step.to(u.s).value
    steps = int(np.ceil(duration_s / step_s))
    offsets = np.unique(np.minimum(np.arange(steps + 1) * step_s, duration_s))
    times = round_time(start + Q_(offsets, "s"))
    interval = P.closedopen(times[0], times[-1])
    warnings = orbit_warnings(scenario, orbit, sat_orbits, times[0], times[-1])

    state = orbit.states(times)
    sun = sun_positions(times)
    sat_states = {}
    for name, source in sat_orbits.items():
        try:
            sat_states[name] = source.states(times, with_velocity=False)
        except ValueError as error:
            raise ValueError(f"satellite target '{name}': {error}") from error
    grid = RunGrid(times, orbit, state, sun, sat_orbits, sat_states)

    def positions_at(at: TimeArray) -> SkyCoord:
        return grid.satellite.states(at, with_velocity=False)

    umbra, eclipses = shadow_intervals(
        times, shadow_cones(state, sun), positions_at, grid.sun
    )
    illumination = {
        "sunlit": interval - eclipses,
        "penumbra": eclipses - umbra,
        "umbra": umbra,
        "eclipse": eclipses,
    }
    latitude, longitude = geodetic(state, grid.earth)
    in_view = target_visibility(scenario, times, state, sat_states, grid)
    events = find_events(
        scenario.activities,
        interval,
        illumination,
        _time_above(times, latitude, positions_at, grid.earth),
        in_view.__getitem__,
    )
    occurrences = resolve_activities(
        scenario.activities, interval, events, illumination, repeat
    )
    slews = []
    if scenario.slew is not None:
        slews = plan_slews(
            occurrences,
            scenario.slew,
            scenario,
            interval,
            grid.satellite.states,
            grid.sun,
            grid.targets,
            grid.earth,
        )
        for window in slews:
            occurrences[window.into] = replace(
                occurrences[window.into],
                slew=window.duration,
                slew_starts_early=window.early,
            )
    illumination_row, attitude, mode = gantt_rows(illumination, occurrences, slews)

    return ScenarioRun(
        scenario=scenario,
        orbit=orbit,
        interval=interval,
        times=times,
        state=state,
        sun=sun,
        latitude=latitude,
        longitude=longitude,
        beta=beta_angle(state, sun),
        eclipses=eclipses,
        sunlit=illumination["sunlit"],
        umbra=umbra,
        penumbra=illumination["penumbra"],
        light=light_fraction(state, sun),
        illumination=illumination_row,
        attitude=attitude,
        mode=mode,
        occurrences=occurrences,
        slews=slews,
        grid=grid,
        activity_table=activity_table(occurrences),
        sat_orbits=sat_orbits,
        sat_states=sat_states,
        in_view=in_view,
        orbit_warnings=warnings,
        repeat=repeat,
    )
