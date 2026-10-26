# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The chain of activities over a run: the events that end them, and each occurrence with
its status.

`docs/scenario/scenario_ref.ipynb`, under "How the events are found" and "The statuses",
explains them.

"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import portion as P
from astropy.units import Quantity

from quicksat import Q_
from quicksat.scenario.activities import Activity
from quicksat.scenario.names import (
    LATITUDE_CROSSING,
    RISE,
    SET,
)
from quicksat.scenario.triggers import Trigger
from quicksat.utils.intervals import (
    TimeArray,
    duration,
    next_start,
    round_time,
)

IlluminationIntervals = dict[str, P.Interval]
"""The illumination of a run, by the constraints' words: `sunlit`, `penumbra`, `umbra`,
and `eclipse`."""

Events = dict[tuple, tuple[P.Interval, ...]]
"""The events of a run, by `Trigger.event_key`, as the intervals whose starts are the
events."""

OUTSIDE_CONSTRAINT = "outside constraint"
"""Status: the activity spends more than `CONSTRAINT_TOLERANCE` outside its
constraint."""

EVENT_NEVER_CAME = "event never came"
"""Status: the event never happens in the run, so the activity runs to the end."""

CUT_AT_END = "cut at end"
"""Status: the activity would run past the end of the run, and is cut there."""

NEGATIVE_DURATION = "negative duration"
"""Status: a negative offset takes the activity's end back to its start, or before it,
so it takes no time."""

SLEW_STARTS_EARLY = "slew starts early"
"""Status: the slew into the activity starts before the activity before it does."""

STATUS_OK = "ok"
"""Status: none of the above."""

CONSTRAINT_TOLERANCE = Q_(1, "s")
"""The time outside a constraint that still counts as none, for numerical effects
only."""


@dataclass(frozen=True)
class Occurrence:
    """
    One activity, as it happens in one pass of the list.

    Parameters
    ----------
    repeat : int
        The pass, from 1
    number : int
        The activity's number in the list, from 1
    activity : Activity
        The activity
    start, end : Time
        Its start and end, on the 1 ms grid
    outside : Quantity or None
        The time outside the constraint, or None without one
    event_never_came : bool
        Whether the ending event never happens in the run
    cut_at_end : bool
        Whether the activity was cut at the end of the run
    slew : Quantity, optional
        The slew into it, settling included, or None
    slew_starts_early : bool, optional
        Whether that slew starts before the activity before it
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
        The occurrence as a closed-open interval, empty if it ends at or before its
        start.
        """
        return P.closedopen(self.start, self.end)

    @property
    def negative_duration(self) -> bool:
        """Whether a negative offset takes the end back to the start, or before it."""
        return bool(self.end <= self.start)

    @property
    def failed(self) -> bool:
        """
        Whether the activity spends more than `CONSTRAINT_TOLERANCE` outside its
        constraint, False without one.
        """
        return self.outside is not None and bool(self.outside > CONSTRAINT_TOLERANCE)

    @property
    def statuses(self) -> list[str]:
        """The occurrence's statuses, as many as apply, or `ok`."""
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


def next_event(intervals: tuple[P.Interval, ...], after: TimeArray) -> TimeArray | None:
    """
    The first event strictly after a time, as the first start of a piece of the
    intervals.

    Parameters
    ----------
    intervals : tuple of portion.Interval
        The intervals whose starts are the events
    after : Time
        One time

    Returns
    -------
    event : Time or None
        The first event after `after`, or None
    """
    starts = [next_start(piece, after) for piece in intervals]
    found = [start for start in starts if start is not None]
    return min(found) if found else None


def find_events(
    activities: list[Activity],
    interval: P.Interval,
    illumination: IlluminationIntervals,
    time_above: Callable[[Quantity], P.Interval],
    time_visible: Callable[[str], P.Interval] | None = None,
) -> Events:
    """
    The events that the triggers name, as the intervals they start, such as the eclipses
    for an eclipse entry.

    The time above each latitude is found once, whichever directions the triggers name.

    Parameters
    ----------
    activities : list of Activity
        One pass of the list
    interval : portion.Interval
        The run, closed-open
    illumination : dict
        The intervals of `sunlit`, `penumbra`, `umbra` and `eclipse`
    time_above : callable
        The time at or above a latitude, as intervals
    time_visible : callable, optional
        The time a target is in view, by name, for `rise` and `set`

    Returns
    -------
    events : dict
        For each event trigger's `event_key`, the intervals whose starts are its events
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
    When a trigger ends an activity that starts at a time: after its duration, or at its
    next event with its offset, or None.
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
    Chain the activities over the run, and check their constraints.

    Each activity starts where the one before ends, and is cut at the end of the run.
    Without repeats, the list runs once. `docs/scenario/scenario_ref.ipynb`, under "The
    activities", gives the rules.

    Parameters
    ----------
    activities : list of Activity
        One pass of the list, which may be empty
    interval : portion.Interval
        The run, closed-open
    events : dict
        The run's events, from `find_events`
    allowed : dict
        The intervals each constraint allows, by name
    repeat : bool, optional
        Whether to repeat the list until the run ends

    Returns
    -------
    occurrences : list of Occurrence
        Every occurrence, in order

    Raises
    ------
    ValueError
        If the list repeats and no activity in it takes any time
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
