# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Helpers for time intervals built with portion.

Every bound is rounded to a 1 ms grid, so the same instant compares equal, and every
interval is closed at its start and open at its end, so touching pieces join.
`docs/scenario/scenario_ref.ipynb` explains why.

"""

from collections.abc import Callable
from typing import Any

import numpy as np
import portion as P
from astropy.time import Time
from astropy.units import Quantity

from quicksat import Q_, u

TimeArray = Any
"""An astropy `Time`, holding one time or an array. It is `Any` for the type checker,
since `Time` has no usable type hints."""

_GRID_ORIGIN = Time("2000-01-01T12:00:00", scale="tt")
"""J2000, the point the 1 ms grid is counted from."""

TIME_GRID = Q_(1, "ms")
"""The spacing of the grid that every interval bound is rounded to."""


def round_time(t: TimeArray) -> TimeArray:
    """
    Round a time to the 1 ms grid, counted from J2000.

    Parameters
    ----------
    t : Time
        One time or an array, in any time scale

    Returns
    -------
    rounded : Time
        The rounded time or times, in TT
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
        A bounded interval with `Time` bounds

    Returns
    -------
    length : Quantity
        In s, rounded to the 1 ms grid, and exactly zero when empty
    """
    seconds = 0.0
    for piece in interval:
        upper: TimeArray = piece.upper
        seconds += float((upper - piece.lower).to_value(u.s))
    step = TIME_GRID.to(u.s).value
    return Q_(np.round(seconds / step) * step, "s")


def labels_at(row: P.IntervalDict, times: TimeArray) -> np.ndarray:
    """
    The value of an `IntervalDict` at each time of an array, compared once per piece for
    speed.

    Parameters
    ----------
    row : portion.IntervalDict
        Time intervals mapped to values, such as the modes
    times : Time
        The sample times, rounded with `round_time`

    Returns
    -------
    labels : ndarray
        One value per time, as objects, None where no piece covers it
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
    When the next piece of an interval begins, strictly after a time, as an event
    trigger finds its event.

    A piece cut by the run's start is never an answer.

    Parameters
    ----------
    intervals : portion.Interval
        Intervals with `Time` bounds, each closed at its start
    after : Time
        One time

    Returns
    -------
    start : Time or None
        The first start after `after`, or None
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
    Where a condition holds over a time grid, with each edge found to 1 ms by bisection
    between the steps.

    A spell shorter than one step can be missed. The cut ends at the grid's first and
    last times are not edges.

    Parameters
    ----------
    times : Time
        The grid's times, in order, rounded with `round_time`
    flags : ndarray
        Whether the condition holds at each time, as bools
    flags_at : callable
        The same flags for any `Time` array

    Returns
    -------
    intervals : portion.Interval
        Where the condition holds, within the grid's span
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
