# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Running a scenario: the orbit, the eclipses and the repeated activities.

`run_scenario` evaluates the orbit on the time grid and finds the umbra and the
penumbra, and the latitude crossings that the triggers name. It repeats the list of activities
until the duration ends and checks each constraint. All the results come back in
one `ScenarioRun`.

Every time interval is closed at its start and open at its end. Every bound goes
through `round_time`. So the pieces of a run fit together with no gaps and no
overlaps.

"""

from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
import portion as P
from astropy.coordinates import CartesianRepresentation, SkyCoord
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.geometry import (
    beta_angle,
    geodetic,
    light_fraction,
    shadow_cones,
    shadow_intervals,
    sun_positions,
)
from quicksat.orbit.sso import sso_tle
from quicksat.orbit.tle import Tle, read_tle_file, warn_if_far_from_epoch
from quicksat.orbit.trajectory import Trajectory
from quicksat.orbit.trajectory_files import read_trajectory_file
from quicksat.scenario.attitude import SLEW, SlewWindow, plan_slews
from quicksat.scenario.config import (
    LATITUDE_CROSSING,
    Activity,
    OrbitCount,
    Scenario,
    Trigger,
)
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
"""Status: the activity spends some time outside its constraint."""

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
        Whether the activity spends any time outside its constraint.

        Returns
        -------
        failed : bool
            False if there is no constraint
        """
        return self.outside is not None and bool(self.outside > Q_(0, "s"))

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

    An element set is read from the TLE file, or built for the sun-synchronous
    orbit, with its epoch at the start of the run. A trajectory is read from the
    trajectory file.

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
        name = f"SSO {sso.altitude:g}, LTAN {sso.ltan:.4g}"
        return sso_tle(round_time(scenario.start), sso.altitude, sso.ltan, name=name)
    if orbit.trajectory_file is not None:
        return read_trajectory_file(orbit.trajectory_file)
    assert orbit.tle_file is not None  # the orbit has exactly one of the three
    return read_tle_file(orbit.tle_file)


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
) -> Events:
    """
    The events that the activities' triggers name, as the intervals they start.

    An eclipse entry is the start of an eclipse, and an eclipse exit the start of
    a sunlit piece. An umbra entry is the start of the umbra, and an umbra exit
    the start of the time outside it. A northward crossing of a latitude is the
    start of the time above it, and a southward crossing is the start of the time
    below it. The time above each latitude is found once, whichever directions the
    triggers name.

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
    for activity in activities:
        trigger = activity.trigger
        key = trigger.event_key
        if key is None or key in events:
            continue
        if trigger.event in shadow_edges:
            events[key] = (shadow_edges[trigger.event],)
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

    A constraint holds when the activity has no time outside the intervals that
    the constraint allows.

    Parameters
    ----------
    activities : list of Activity
        One repeat of the list
    interval : portion.Interval
        The run, closed at its start and open at its end
    events : dict
        The events of the run, from `find_events`
    allowed : dict
        The intervals that each constraint allows, by the name of the constraint

    Returns
    -------
    occurrences : list of Occurrence
        Every occurrence, in order, from the start of the run to its end

    Raises
    ------
    ValueError
        If no activity in the list ends after it starts. The run would then never
        move on.
    """
    run_end: TimeArray = interval.upper
    occurrences = []
    start: TimeArray = interval.lower
    repeat_start = start
    index, repeat = 0, 1
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
                repeat, index + 1, activity, start, end, outside, never_came, cut
            )
        )

        # an activity that ends before it starts takes no time
        start = max(start, end)
        index += 1
        if index == len(activities):
            if start == repeat_start:
                raise ValueError(
                    "No activity in the list ends after it starts, so the run never "
                    f"moves on from {start.utc.isot}. Every activity has a negative "
                    "offset that takes its end back to its start or before it. "
                    "Shorten the offsets."
                )
            index, repeat, repeat_start = 0, repeat + 1, start
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
        The columns are the repeat and activity numbers, the start and end as UTC
        text, the duration in minutes, the trigger as written, the attitude, the
        time of the slew into it in seconds, the mode, the constraint, the time
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
                "mode": activity.mode,
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
    repeats = occurrences[-1].repeat
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
) -> tuple[P.IntervalDict, P.IntervalDict, P.IntervalDict]:
    """
    Build the three rows of the Gantt chart.

    Each row has exactly one value at any time of the run. Touching pieces with
    the same value merge into one.

    Parameters
    ----------
    illumination : dict
        The intervals of `sunlit`, `penumbra` and `umbra`
    occurrences : list of Occurrence
        The occurrences from `resolve_activities`
    slews : list of SlewWindow
        The slews, from `plan_slews`. They take the attitude row's time over
        from the activities.

    Returns
    -------
    illumination : portion.IntervalDict
        `sunlit`, `penumbra` and `umbra`
    attitude : portion.IntervalDict
        The attitude names, and `slew` while the body turns or settles
    mode : portion.IntervalDict
        The mode names
    """
    row = P.IntervalDict()
    for state in ("sunlit", "penumbra", "umbra"):
        row[illumination[state]] = state
    attitude = P.IntervalDict()
    mode = P.IntervalDict()
    for occurrence in occurrences:
        attitude[occurrence.interval] = occurrence.activity.attitude
        mode[occurrence.interval] = occurrence.activity.mode
    for window in slews:
        attitude[window.interval] = SLEW
    return row, attitude, mode


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
    illumination, attitude, mode : portion.IntervalDict
        The three rows of the Gantt chart
    occurrences : list of Occurrence
        Every activity as it happens in the run
    slews : list of SlewWindow
        Every slew between attitudes, in time order. Empty when the scenario has
        no slews.
    activity_table : pd.DataFrame
        The occurrences as a table, from `activity_table`
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
    mode: P.IntervalDict
    occurrences: list[Occurrence]
    slews: list[SlewWindow]
    activity_table: pd.DataFrame

    @property
    def activity_summary(self) -> str:
        """
        One line that sums up the occurrences, from `activity_summary`.

        Returns
        -------
        summary : str
        """
        return activity_summary(self.occurrences)


def run_scenario(scenario: Scenario) -> ScenarioRun:  # noqa: V103
    """
    Run a scenario.

    The orbit comes from the TLE file, from a TLE built for the sun-synchronous
    orbit, or from the trajectory file. It is evaluated on the time grid, with
    SGP4 or by interpolation. The edges of the umbra and the penumbra are then
    located between the grid steps, and so are the latitude crossings that the
    triggers name. The activities are then repeated over the run and checked
    against the eclipses. The run gets a warning if it starts more than 7 days
    from the epoch of the TLE, or comes close to an end of the trajectory.

    Parameters
    ----------
    scenario : Scenario
        The scenario, from `Scenario.from_yaml_file`

    Returns
    -------
    result : ScenarioRun
        The orbit, the eclipses, the activities and the checks

    Raises
    ------
    ValueError
        If no activity in the list ends after it starts, or if the run does not
        lie inside the trajectory
    """
    orbit = scenario_orbit(scenario)
    start = round_time(scenario.start)
    if isinstance(orbit, Tle):
        warn_if_far_from_epoch(orbit, start)

    duration_s = run_length(scenario, orbit).to(u.s).value
    step_s = scenario.step.to(u.s).value
    steps = int(np.ceil(duration_s / step_s))
    offsets = np.unique(np.minimum(np.arange(steps + 1) * step_s, duration_s))
    times = round_time(start + Q_(offsets, "s"))
    interval = P.closedopen(times[0], times[-1])
    if isinstance(orbit, Trajectory):
        orbit.check_covers(times[0], times[-1])

    def positions_at(at: TimeArray) -> SkyCoord:
        return orbit.states(at, with_velocity=False)

    state = orbit.states(times)
    sun = sun_positions(times)
    umbra, eclipses = shadow_intervals(times, shadow_cones(state, sun), positions_at)
    illumination = {
        "sunlit": interval - eclipses,
        "penumbra": eclipses - umbra,
        "umbra": umbra,
        "eclipse": eclipses,
    }
    latitude, longitude = geodetic(state)

    def time_above(limit: Quantity) -> P.Interval:
        def above_at(at: TimeArray) -> np.ndarray:
            return np.asarray(geodetic(positions_at(at))[0] >= limit)

        return intervals_where(times, np.asarray(latitude >= limit), above_at)

    events = find_events(scenario.activities, interval, illumination, time_above)
    occurrences = resolve_activities(
        scenario.activities, interval, events, illumination
    )
    slews = []
    if scenario.slew is not None:

        def states_at(at: TimeArray) -> SkyCoord:
            return orbit.states(at)

        slews = plan_slews(
            occurrences,
            scenario.slew,
            scenario.attitudes,
            interval,
            states_at,
            sun_positions,
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
        activity_table=activity_table(occurrences),
    )
