# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the interval helpers.

The intervals here are built by hand on a clock that starts at `T0`, so each
expected time follows from the numbers alone.
"""

import numpy as np
import portion as P
import pytest
from astropy.time import Time

from quicksat import Q_, u
from quicksat.utils.intervals import (
    duration,
    intervals_where,
    labels_at,
    next_start,
    round_time,
)

T0 = round_time(Time("2026-10-01T00:00:00", scale="utc"))


def at(seconds):
    """A time, or an array of times, that many seconds after `T0`, rounded."""
    return round_time(T0 + Q_(seconds, "s"))


def seconds(time):
    """Seconds from `T0`."""
    return float((time - T0).to_value(u.s))


# ---------------------------------------------------------------- round_time


def test_round_time_puts_two_routes_to_one_instant_on_the_same_value():
    one_step = round_time(T0 + Q_(0.3, "s"))
    two_steps = round_time(T0 + Q_(0.1, "s") + Q_(0.2, "s"))
    assert one_step == two_steps


def test_round_time_moves_a_time_by_at_most_half_a_millisecond():
    time = T0 + Q_(12.3456789, "s")
    rounded = round_time(time)
    assert abs(float((rounded - time).to_value(u.ms))) <= 0.5
    # astropy subtracts times with tens of nanoseconds of float noise
    assert seconds(rounded) == pytest.approx(12.346, abs=1e-6)


def test_round_time_changes_nothing_the_second_time():
    once = round_time(T0 + Q_(7.0004, "s"))
    assert round_time(once) == once


# ---------------------------------------------------------------- duration


def test_duration_adds_up_the_pieces():
    intervals = P.closedopen(at(0), at(10)) | P.closedopen(at(20), at(25.5))
    assert duration(intervals) == Q_(15.5, "s")


def test_duration_of_nothing_is_zero():
    assert duration(P.empty()) == Q_(0, "s")


# ---------------------------------------------------------------- labels_at


def test_labels_at_follows_closed_starts_and_open_ends():
    row = P.IntervalDict()
    row[P.closedopen(at(0), at(10))] = "a"
    row[P.closedopen(at(10), at(20))] = "b"
    labels = labels_at(row, at(np.array([0, 5, 10, 19.999, 20, 30])))
    assert list(labels) == ["a", "a", "b", "b", None, None]


# ---------------------------------------------------------------- next_start


@pytest.fixture
def pieces():
    """Two pieces, the first cut by the start of the clock."""
    return P.closedopen(at(0), at(10)) | P.closedopen(at(30), at(40))


def test_next_start_finds_the_next_piece(pieces):
    assert seconds(next_start(pieces, at(5))) == pytest.approx(30)


def test_next_start_looks_strictly_after_the_time(pieces):
    # A piece that starts at the time itself is not next
    assert next_start(pieces, at(30)) is None


def test_next_start_never_takes_a_piece_cut_at_the_start(pieces):
    # The first piece starts at T0, so from T0 the next start is the second piece
    assert seconds(next_start(pieces, at(0))) == pytest.approx(30)


def test_next_start_gives_none_when_nothing_follows(pieces):
    assert next_start(pieces, at(35)) is None


# ---------------------------------------------------------------- intervals_where


PERIOD = 100.0
"""Period of the test condition, in seconds: true over the first half of each."""


def condition(times):
    """True while a sine of period `PERIOD`, offset by a quarter second, is positive."""
    phase = 2 * np.pi * ((times - T0).to_value(u.s) - 0.25) / PERIOD
    return np.sin(phase) > 0


def test_intervals_where_locates_each_edge_to_a_millisecond():
    grid = at(np.arange(0, 301, 10.0))
    holds = intervals_where(grid, condition(grid), condition)
    # the condition holds from 0.25 s to 50.25 s, and so on every 100 s
    starts = [seconds(piece.lower) for piece in holds]
    ends = [seconds(piece.upper) for piece in holds]
    assert starts == pytest.approx([0.25, 100.25, 200.25], abs=1e-3)
    assert ends == pytest.approx([50.25, 150.25, 250.25], abs=1e-3)


def test_intervals_where_does_not_depend_on_the_step():
    coarse = at(np.arange(0, 301, 20.0))
    fine = at(np.arange(0, 301, 1.0))
    from_coarse = intervals_where(coarse, condition(coarse), condition)
    from_fine = intervals_where(fine, condition(fine), condition)
    assert from_coarse == from_fine


def test_intervals_where_cuts_pieces_at_the_ends_of_the_grid():
    grid = at(np.arange(10, 141, 10.0))
    holds = intervals_where(grid, condition(grid), condition)
    first, last = list(holds)[0], list(holds)[-1]
    # under way at the first time, and still under way at the last
    assert first.lower == grid[0]
    assert last.upper == grid[-1]
    # and the cut start is not an event
    assert seconds(next_start(holds, grid[0])) == pytest.approx(100.25, abs=1e-3)


def test_intervals_where_with_no_change_is_all_or_nothing():
    grid = at(np.arange(0, 41, 10.0))
    always = np.ones(len(grid), dtype=bool)
    assert intervals_where(grid, always, condition) == P.closedopen(grid[0], grid[-1])
    assert intervals_where(grid, ~always, condition) == P.empty()
