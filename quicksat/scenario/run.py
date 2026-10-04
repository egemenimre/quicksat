# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Running a scenario: the orbit, the eclipses and the repeated activities.

`run_scenario` evaluates the orbit on the time grid and finds the eclipses, and
the latitude crossings that the triggers name. It repeats the list of activities
until the duration ends and checks each constraint. All the results come back in
one `ScenarioRun`.

Every time interval is closed at its start and open at its end. Every bound goes
through `round_time`. So the pieces of a run fit together with no gaps and no
overlaps.

"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import portion as P
from astropy.coordinates import CartesianRepresentation, SkyCoord
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.geometry import (
    beta_angle,
    eclipse_intervals,
    geodetic,
    in_shadow,
    sun_positions,
)
from quicksat.orbit.sso import sso_tle
from quicksat.orbit.tle import Tle, read_tle_file, tle_states, warn_if_far_from_epoch
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
        Start and end, on the 1 ms grid
    outside : Quantity or None
        Total time spent outside the constraint, or None if there is no constraint
    event_never_came : bool
        True if the event that ends the activity never happens in the run
    cut_at_end : bool
        True if the activity would have ended after the end of the run. That
        includes an event that happens in the run, but not again before its end.
    """

    repeat: int
    number: int
    activity: Activity
    start: TimeArray
    end: TimeArray
    outside: Quantity | None
    event_never_came: bool
    cut_at_end: bool

    @property
    def interval(self) -> P.Interval:
        """
        The occurrence as a time interval, closed at its start and open at its end.

        Returns
        -------
        interval : portion.Interval
        """
        return P.closedopen(self.start, self.end)

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
            `outside constraint`, `event never came` and `cut at end`, as far as
            they apply, or `ok` if none does
        """
        statuses = []
        if self.failed:
            statuses.append(OUTSIDE_CONSTRAINT)
        if self.event_never_came:
            statuses.append(EVENT_NEVER_CAME)
        if self.cut_at_end:
            statuses.append(CUT_AT_END)
        return statuses or [STATUS_OK]


def scenario_tle(scenario: Scenario) -> Tle:
    """
    The element set of the scenario's orbit.

    It is read from the TLE file, or built for the sun-synchronous orbit. A built
    TLE has its epoch at the start of the run.

    Parameters
    ----------
    scenario : Scenario
        The scenario

    Returns
    -------
    tle : Tle
        The element set
    """
    orbit = scenario.orbit
    if orbit.sso is not None:
        sso = orbit.sso
        name = f"SSO {sso.altitude:g}, LTAN {sso.ltan:.4g}"
        return sso_tle(round_time(scenario.start), sso.altitude, sso.ltan, name=name)
    assert orbit.tle_file is not None  # the orbit has exactly one of the two
    return read_tle_file(orbit.tle_file)


def run_length(scenario: Scenario, tle: Tle) -> Quantity:
    """
    The length of the run, as a time.

    A duration given as a time is used as it is. A number of orbits is multiplied
    by the nodal period of the element set.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    tle : Tle
        The element set of the scenario's orbit

    Returns
    -------
    length : Quantity
        The length of the run, in seconds

    Raises
    ------
    ValueError
        If the step is not shorter than the run
    """
    duration = scenario.duration
    if isinstance(duration, OrbitCount):
        length = Q_(duration.count * tle.nodal_period.to(u.s).value, "s")
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
    eclipses: P.Interval,
    sunlit: P.Interval,
    time_above: Callable[[Quantity], P.Interval],
) -> Events:
    """
    The events that the activities' triggers name, as the intervals they start.

    An eclipse entry is the start of an eclipse, and an eclipse exit is the start
    of a sunlit piece. A northward crossing of a latitude is the start of the time
    above it, and a southward crossing is the start of the time below it. The time
    above each latitude is found once, whichever directions the triggers name.

    Parameters
    ----------
    activities : list of Activity
        One repeat of the list
    interval : portion.Interval
        The run, closed at its start and open at its end
    eclipses, sunlit : portion.Interval
        The illumination intervals
    time_above : callable
        Gives the time at or above a geodetic latitude, as intervals over the run

    Returns
    -------
    events : dict
        For the `event_key` of each event trigger, the intervals whose starts are
        its events
    """
    events: Events = {}
    above: dict[float, P.Interval] = {}
    for activity in activities:
        trigger = activity.trigger
        key = trigger.event_key
        if key is None or key in events:
            continue
        if trigger.event == "eclipse entry":
            events[key] = (eclipses,)
        elif trigger.event == "eclipse exit":
            events[key] = (sunlit,)
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
        If a negative offset ends an activity at or before its start
    """
    run_end: TimeArray = interval.upper
    occurrences = []
    start: TimeArray = interval.lower
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
            if end <= start:
                # only a negative offset can do this
                raise ValueError(
                    f"Activity {index + 1} of repeat {repeat}, '{trigger.text}', ends "
                    f"{(start - end).to_value(u.s):.3f} s before it starts. It starts "
                    f"at {start.utc.isot} and would end at {end.utc.isot}. Its "
                    "offset takes the end back to the start or before it. Shorten "
                    "the offset, or add an activity before this one."
                )
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

        start = end
        index += 1
        if index == len(activities):
            index, repeat = 0, repeat + 1
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
        mode, the constraint, the time outside the constraint in seconds, and the
        status. The status is `ok`, or any of `outside constraint`,
        `event never came` and `cut at end`, joined by commas. The constraint is
        blank and the time outside is NaN where an activity has no constraint.
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
                "duration [min]": duration(occurrence.interval).to_value(u.min),
                "trigger": activity.trigger.text,
                "attitude": activity.attitude,
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
        The number of occurrences and repeats, and how many are outside their
        constraint, saw an event that never came, or were cut at the end
    """
    failed = sum(occurrence.failed for occurrence in occurrences)
    never_came = sum(occurrence.event_never_came for occurrence in occurrences)
    cut = sum(occurrence.cut_at_end for occurrence in occurrences)
    return (
        f"Occurrences: {len(occurrences)} in {occurrences[-1].repeat} repeats. "
        f"{OUTSIDE_CONSTRAINT.capitalize()}: {failed}. "
        f"{EVENT_NEVER_CAME.capitalize()}: {never_came}. "
        f"{CUT_AT_END.capitalize()}: {cut}."
    )


def gantt_rows(
    sunlit: P.Interval, eclipses: P.Interval, occurrences: list[Occurrence]
) -> tuple[P.IntervalDict, P.IntervalDict, P.IntervalDict]:
    """
    Build the three rows of the Gantt chart.

    Each row has exactly one value at any time of the run. Touching pieces with
    the same value merge into one.

    Parameters
    ----------
    sunlit, eclipses : portion.Interval
        The illumination intervals
    occurrences : list of Occurrence
        The occurrences from `resolve_activities`

    Returns
    -------
    illumination : portion.IntervalDict
        `sunlit` and `eclipse`
    attitude : portion.IntervalDict
        The attitude names
    mode : portion.IntervalDict
        The mode names
    """
    illumination = P.IntervalDict()
    illumination[sunlit] = "sunlit"
    illumination[eclipses] = "eclipse"
    attitude = P.IntervalDict()
    mode = P.IntervalDict()
    for occurrence in occurrences:
        attitude[occurrence.interval] = occurrence.activity.attitude
        mode[occurrence.interval] = occurrence.activity.mode
    return illumination, attitude, mode


@dataclass(frozen=True)
class ScenarioRun:
    """
    Everything that running a scenario produces.

    Parameters
    ----------
    scenario : Scenario
        The scenario that was run
    tle : Tle
        The element set the orbit comes from
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
    illumination, attitude, mode : portion.IntervalDict
        The three rows of the Gantt chart
    occurrences : list of Occurrence
        Every activity as it happens in the run
    activity_table : pd.DataFrame
        The occurrences as a table, from `activity_table`
    """

    scenario: Scenario
    tle: Tle
    interval: P.Interval
    times: TimeArray
    state: SkyCoord
    sun: CartesianRepresentation
    latitude: Quantity
    longitude: Quantity
    beta: Quantity  # noqa: V107
    eclipses: P.Interval
    sunlit: P.Interval
    illumination: P.IntervalDict
    attitude: P.IntervalDict
    mode: P.IntervalDict
    occurrences: list[Occurrence]
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

    The orbit comes from the TLE file, or from a TLE built for the
    sun-synchronous orbit. It is evaluated on the time grid with SGP4. The eclipse
    entries and exits are then located between the grid steps, and so are the
    latitude crossings that the triggers name. The activities are then repeated
    over the run and checked against the eclipses. The run gets a warning if it
    starts more than 7 days from the epoch of the TLE.

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
        If a negative offset ends an activity at or before its start
    """
    tle = scenario_tle(scenario)
    start = round_time(scenario.start)
    warn_if_far_from_epoch(tle, start)

    duration_s = run_length(scenario, tle).to(u.s).value
    step_s = scenario.step.to(u.s).value
    steps = int(np.ceil(duration_s / step_s))
    offsets = np.unique(np.minimum(np.arange(steps + 1) * step_s, duration_s))
    times = round_time(start + Q_(offsets, "s"))
    interval = P.closedopen(times[0], times[-1])

    def positions_at(at: TimeArray) -> SkyCoord:
        return tle_states(tle, at, with_velocity=False)

    state = tle_states(tle, times)
    sun = sun_positions(times)
    shadow = in_shadow(state, sun)
    eclipses = eclipse_intervals(times, shadow, positions_at)
    sunlit = interval - eclipses
    latitude, longitude = geodetic(state)

    def time_above(limit: Quantity) -> P.Interval:
        def above_at(at: TimeArray) -> np.ndarray:
            return np.asarray(geodetic(positions_at(at))[0] >= limit)

        return intervals_where(times, np.asarray(latitude >= limit), above_at)

    events = find_events(scenario.activities, interval, eclipses, sunlit, time_above)
    occurrences = resolve_activities(
        scenario.activities,
        interval,
        events,
        {"sunlit": sunlit, "eclipse": eclipses},
    )
    illumination, attitude, mode = gantt_rows(sunlit, eclipses, occurrences)

    return ScenarioRun(
        scenario=scenario,
        tle=tle,
        interval=interval,
        times=times,
        state=state,
        sun=sun,
        latitude=latitude,
        longitude=longitude,
        beta=beta_angle(state, sun),
        eclipses=eclipses,
        sunlit=sunlit,
        illumination=illumination,
        attitude=attitude,
        mode=mode,
        occurrences=occurrences,
        activity_table=activity_table(occurrences),
    )
