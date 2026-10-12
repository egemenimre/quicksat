# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The time of a scenario run in seconds, its whole orbits, and energy over time.

Generation, consumption and the power budget all report each whole orbit, so
they count the orbits the same way: from the start of the run, one period each.
A cut orbit at the end of the run is left out. A part of an orbit would skew a
mean: in the Orekit case of `tests/power/data/`, a whole day rather than whole
orbits moves a panel's mean by up to 3.4%.

Times here are seconds from the start of the run, as floats.

"""

import numpy as np
import portion as P

from quicksat import u
from quicksat.scenario.run import ScenarioRun
from quicksat.utils.intervals import TIME_GRID


def run_seconds(run: ScenarioRun) -> np.ndarray:
    """
    The run's grid, in seconds from its start.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    seconds : ndarray
        One for each time of the grid, rising, from 0
    """
    return np.asarray((run.times - run.times[0]).to_value(u.s))


def interval_pieces(
    run: ScenarioRun, intervals: P.Interval
) -> list[tuple[float, float]]:
    """
    The pieces of an interval of the run, in seconds from its start.

    Parameters
    ----------
    run : ScenarioRun
        The run
    intervals : portion.Interval
        Time intervals inside the run, such as `run.eclipses`

    Returns
    -------
    pieces : list of tuple of float
        The start and the end of each piece
    """
    start = run.times[0]
    return [
        (
            float((piece.lower - start).to_value(u.s)),
            float((piece.upper - start).to_value(u.s)),
        )
        for piece in intervals
        if not piece.empty
    ]


def whole_orbits(run: ScenarioRun) -> list[tuple[float, float]]:
    """
    The whole orbits in a run, counted from its start, one period each.

    A cut orbit at the end of the run is left out. So is every orbit of a run
    shorter than one period.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    orbits : list of tuple of float
        The start and the end of each orbit, in seconds from the run's start
    """
    period = float(run.orbit.period.to(u.s).value)
    length = float((run.times[-1] - run.times[0]).to_value(u.s))
    # the end of the run sits on the 1 ms grid, so it may fall short of a whole
    # number of periods by up to 1 ms
    count = int((length + float(TIME_GRID.to(u.s).value)) // period)
    return [
        (number * period, min((number + 1) * period, length)) for number in range(count)
    ]


def overlap(pieces: list[tuple[float, float]], start: float, end: float) -> float:
    """
    The time that some pieces spend between two times.

    Parameters
    ----------
    pieces : list of tuple of float
        The start and the end of each piece, in seconds
    start, end : float
        The window, in seconds

    Returns
    -------
    time : float
        In seconds
    """
    return sum(max(0.0, min(upper, end) - max(lower, start)) for lower, upper in pieces)


def energy_until(seconds: np.ndarray, power: np.ndarray, at: np.ndarray) -> np.ndarray:
    """
    The energy from the start of the grid up to each given time, in joules.

    The power is taken to change linearly between the times of the grid, so the
    energy is exact for it, also between those times.

    Parameters
    ----------
    seconds : ndarray
        The times of the grid, in seconds from its start, rising
    power : ndarray
        The power at each time of the grid, in watts
    at : ndarray
        The times to give the energy at, in seconds, inside the grid

    Returns
    -------
    energy : ndarray
        In joules, one for each time in `at`
    """
    steps = np.diff(seconds)
    gained = np.concatenate([[0.0], np.cumsum((power[1:] + power[:-1]) / 2 * steps)])
    index = np.clip(np.searchsorted(seconds, at, side="right") - 1, 0, len(steps) - 1)
    into = at - seconds[index]
    slope = (power[index + 1] - power[index]) / steps[index]
    return gained[index] + power[index] * into + slope * into**2 / 2
