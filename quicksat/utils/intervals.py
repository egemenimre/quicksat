# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Helpers for time intervals built with portion.

Eclipses and activities are both time intervals, and portion does the set
arithmetic on them. That covers union, intersection and difference. portion takes
astropy `Time` values as bounds, but it compares them exactly. Two values for the
same instant often differ by a few picoseconds. Rounding every bound to one fixed
grid removes that problem, so plain portion is enough.

The helpers here round a time and add up the length of an interval. They also
look up the value of an `IntervalDict` at every time of a `Time` array, and find
when the next piece of an interval begins. `intervals_where` finds where a
condition holds, such as the shadow or a latitude limit, with its edges located
between the steps of a time grid.

Every interval in quicksat is closed at its start and open at its end, made with
`P.closedopen`. So touching intervals join. The pieces of a run then fit together
without gaps or overlaps.

"""

from collections.abc import Callable
from typing import Any

import numpy as np
import portion as P
from astropy.time import Time
from astropy.units import Quantity

from quicksat import Q_, u

TimeArray = Any
"""An astropy `Time`, holding one time or an array of times.

astropy's `Time` has no usable type hints: a type checker reads `times[0]` as
`None`, and `time.utc` as an array. So the package annotates its times with this
alias, which is `Any` for the checker. The docstrings say whether a single time or
an array is meant.
"""

_GRID_ORIGIN = Time("2000-01-01T12:00:00", scale="tt")
"""J2000, the point the 1 ms grid is counted from."""

TIME_GRID = Q_(1, "ms")
"""Spacing of the grid that every interval bound is rounded to."""


def round_time(t: TimeArray) -> TimeArray:
    """
    Round a time to the 1 ms grid, counted from J2000.

    Two values for the same instant then compare exactly equal, whichever way they
    were worked out. Rounding twice changes nothing, and a time moves by at most
    half a millisecond.

    Parameters
    ----------
    t : Time
        A single time or an array of times, in any time scale

    Returns
    -------
    rounded : Time
        The rounded time or times, in the TT time scale
    """
    step = TIME_GRID.to(u.s).value
    seconds = (t - _GRID_ORIGIN).to_value(u.s)
    return _GRID_ORIGIN + Q_(np.round(seconds / step) * step, "s")


def duration(interval: P.Interval) -> Quantity:
    """
    Total length of all the pieces of an interval.

    Parameters
    ----------
    interval : portion.Interval
        An interval with `Time` bounds, in one piece or in many. It must not be
        unbounded.

    Returns
    -------
    length : Quantity
        The summed length, in seconds, rounded to the 1 ms grid. Every bound is on
        that grid, so the rounding only removes the float noise of the subtraction.
        An empty interval gives exactly zero.
    """
    seconds = 0.0
    for piece in interval:
        upper: TimeArray = piece.upper
        seconds += float((upper - piece.lower).to_value(u.s))
    step = TIME_GRID.to(u.s).value
    return Q_(np.round(seconds / step) * step, "s")


def labels_at(row: P.IntervalDict, times: TimeArray) -> np.ndarray:
    """
    Value of an `IntervalDict` at each time of a `Time` array.

    portion takes only single times as bounds, and looking up one sample at a time
    is slow. This compares the whole array once for each piece of the row, which
    is about a thousand times faster. The values are assumed not to overlap, as in
    any `IntervalDict`.

    Parameters
    ----------
    row : portion.IntervalDict
        A row mapping time intervals to values, such as a mode or an attitude name
    times : Time
        The sample times, as an array. They should have been through `round_time`,
        so that a sample on a boundary compares exactly.

    Returns
    -------
    labels : ndarray
        One value for each time, as an array of objects. A time that no piece of
        the row covers gets `None`.
    """
    labels = np.full(times.shape, None, dtype=object)
    for interval, value in row.items():
        for piece in interval:
            after_start = (
                times >= piece.lower if piece.left == P.CLOSED else times > piece.lower
            )
            before_end = (
                times <= piece.upper if piece.right == P.CLOSED else times < piece.upper
            )
            labels[after_start & before_end] = value
    return labels


def next_start(intervals: P.Interval, after: TimeArray) -> TimeArray | None:
    """
    When the next piece of an interval begins, strictly after a given time.

    Intersecting with the open interval from `after` onwards does the work. A piece
    that began at or before `after` comes out open at its start. A piece that
    begins later keeps its closed start. So the first closed start is the answer.
    A piece cut by the start of the run is never an answer either, because no
    activity starts before the run.

    This is how an event trigger finds its event. An eclipse entry is the start of
    an eclipse, and an eclipse exit is the start of a sunlit piece.

    Parameters
    ----------
    intervals : portion.Interval
        Intervals with `Time` bounds, each closed at its start
    after : Time
        A single time

    Returns
    -------
    start : Time or None
        The first start after `after`, or None if no piece begins after it
    """
    for piece in intervals & P.open(after, P.inf):
        if piece.left == P.CLOSED:
            return piece.lower
    return None


def intervals_where(
    times: TimeArray,
    flags: np.ndarray,
    flags_at: Callable[[TimeArray], np.ndarray],
) -> P.Interval:
    """
    Where a condition holds over the span of a time grid, as portion intervals.

    Wherever the flag changes between two grid steps, one edge lies between them.
    All the brackets are halved together by bisection. Each midpoint evaluates
    the condition again, with `flags_at`, so the result does not depend on the
    step. The search stops once every bracket is shorter than 1 ms. It then takes
    the midpoint and rounds it with `round_time`.

    It assumes that no bracket holds two edges. That holds for any step far
    shorter than the time the condition holds or fails. A spell shorter than one
    step can be missed.

    Each piece is closed at its start and open at its end. A piece already under
    way at the first time begins there, and one still under way at the last time
    ends there. These cut ends are not edges, and `next_start` never takes them
    for an event.

    Parameters
    ----------
    times : Time
        The grid times, in order, rounded with `round_time`
    flags : ndarray
        Whether the condition holds at each grid time, as an array of bools
    flags_at : callable
        Gives the same flags for any `Time` array

    Returns
    -------
    intervals : portion.Interval
        Where the condition holds, between the first and the last time of the grid
    """
    changed = np.flatnonzero(flags[:-1] != flags[1:])
    rises = ~flags[changed]
    epoch = times[0]
    low = (times[changed] - epoch).to_value(u.s)
    high = (times[changed + 1] - epoch).to_value(u.s)
    tolerance = TIME_GRID.to(u.s).value
    while changed.size and (high - low).max() >= tolerance:
        middle = 0.5 * (low + high)
        mid_flags = flags_at(epoch + Q_(middle, "s"))
        # a rise is false at the low end and true at the high end, a fall the reverse
        move_high = mid_flags == rises
        high = np.where(move_high, middle, high)
        low = np.where(move_high, low, middle)
    edges = round_time(epoch + Q_(0.5 * (low + high), "s"))

    begins = list(edges[rises])
    ends = list(edges[~rises])
    if flags[0]:
        begins.insert(0, times[0])
    if flags[-1]:
        ends.append(times[-1])
    holds = P.empty()
    for begin, end in zip(begins, ends, strict=True):
        holds |= P.closedopen(begin, end)
    return holds
