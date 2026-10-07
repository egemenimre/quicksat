# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for reading TLE files and propagating them.

The reference is a 510 km sun-synchronous TLE with its epoch at 2026-10-01
00:00 UTC. Its nodal period is 94.8525 min.
"""

import warnings
from typing import cast

import numpy as np
import pytest
from astropy.coordinates import GCRS, CartesianRepresentation
from astropy.tests.helper import assert_quantity_allclose
from astropy.time import Time

from quicksat import Q_, R_EARTH, u
from quicksat.orbit.tle import read_tle_file, tle_states, warn_if_far_from_epoch

NAME = "SAMPLE SAT"


def write(path, lines):
    """Write the lines to a file and return its path."""
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def lines(data_dir):
    """The two lines of the reference TLE."""
    return data_dir.joinpath("sso_510km.tle").read_text().splitlines()


def test_a_two_line_file_has_no_name(tle):
    assert tle.name is None
    assert tle.epoch.utc.isot == "2026-10-01T00:00:00.000"


def test_a_three_line_file_keeps_its_name(tmp_path, lines):
    tle = read_tle_file(write(tmp_path / "named.tle", [NAME, *lines]))
    assert tle.name == NAME


def test_the_nodal_period_comes_from_sgp4s_secular_rates(tle):
    assert_quantity_allclose(tle.nodal_period, Q_(94.8525, "min"), atol=Q_(1e-4, "min"))


def test_the_lines_written_back_read_the_same(tmp_path, tle):
    again = read_tle_file(write(tmp_path / "again.tle", list(tle.lines)))
    assert again.lines == tle.lines


def test_a_wrong_checksum_is_refused_with_the_file_name(tmp_path, lines):
    broken = lines[1][:-1] + str((int(lines[1][-1]) + 1) % 10)
    path = write(tmp_path / "broken.tle", [lines[0], broken])
    with pytest.raises(ValueError, match="broken.tle"):
        read_tle_file(path)


def test_a_name_after_the_lines_is_refused(tmp_path, lines):
    with pytest.raises(ValueError, match="name line must come first"):
        read_tle_file(write(tmp_path / "late.tle", [*lines, NAME]))


def test_two_tles_in_one_file_are_refused(tmp_path, lines):
    with pytest.raises(ValueError, match="exactly one TLE"):
        read_tle_file(write(tmp_path / "two.tle", lines + lines))


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_tle_file(tmp_path / "nowhere.tle")


def test_states_are_in_gcrs_with_or_without_velocity(tle):
    times = tle.epoch + np.arange(10) * u.min
    state = tle_states(tle, times)
    cartesian = cast(CartesianRepresentation, state.cartesian)
    positions = tle_states(tle, times, with_velocity=False)
    assert isinstance(state.frame, GCRS)
    assert state.shape == (10,)
    assert "s" in cartesian.differentials
    assert not cast(CartesianRepresentation, positions.cartesian).differentials
    altitude = cartesian.norm() - R_EARTH
    assert np.all((altitude > Q_(495, "km")) & (altitude < Q_(525, "km")))


def test_a_start_far_from_the_epoch_warns(tle):
    with pytest.warns(UserWarning, match="days from the TLE epoch"):
        warn_if_far_from_epoch(tle, Time("2026-10-10T00:00:00", scale="utc"))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_far_from_epoch(tle, Time("2026-10-06T00:00:00", scale="utc"))
