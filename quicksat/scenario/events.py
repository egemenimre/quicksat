# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The chain of activities over a run: the events that end them, and each
occurrence with its status.

`find_events` finds the events that the triggers name. `resolve_activities` then
chains the activities, each starting where the one before it ends, and gives
each occurrence its status.

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
    illumination: IlluminationIntervals,
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
