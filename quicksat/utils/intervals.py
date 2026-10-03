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
when the next piece of an interval begins.

Every interval in quicksat is closed at its start and open at its end, made with
`P.closedopen`. So touching intervals join. The pieces of a run then fit together
without gaps or overlaps.

"""

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
