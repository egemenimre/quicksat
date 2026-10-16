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
from sgp4.io import compute_checksum

from quicksat import Q_, R_EARTH, u
from quicksat.orbit.tle import (
    read_tle_file,
    read_tle_sets,
    tle_states,
    warn_if_far_from_epoch,
)

NAME = "SAMPLE SAT"


def write(path, lines):
    """Write the lines to a file and return its path."""
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def lines(data_dir):
    """The two lines of the reference TLE."""
    return data_dir.joinpath("sso_510km.tle").read_text().splitlines()


def variant(lines, number, day="274.00000000"):
    """
    The reference TLE's two lines, with another catalogue number and another day
    of 2026 for the epoch, and their checksums mended.
    """
    line1 = f"{lines[0][:2]}{number:05d}{lines[0][7:20]}{day}{lines[0][32:68]}"
    line2 = f"{lines[1][:2]}{number:05d}{lines[1][7:68]}"
    return [line + str(compute_checksum(line)) for line in (line1, line2)]


@pytest.fixture
def group(tmp_path, lines):
    """
    A file of three TLEs, as a group from CelesTrak or Space-Track: one with
    Space-Track's `0 ` in front of its name, one with a padded name, and one
    with no name line.
    """
    return write(
        tmp_path / "relays.tle",
        [
            "0 RELAY-01",
            *variant(lines, 90001),
            "RELAY-02                ",
            *variant(lines, 90002),
            "",
            *variant(lines, 90003),
        ],
    )


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


def test_a_wrong_checksum_is_refused_with_the_file_and_the_line(tmp_path, lines):
    broken = lines[1][:-1] + str((int(lines[1][-1]) + 1) % 10)
    path = write(tmp_path / "broken.tle", [NAME, lines[0], broken])
    with pytest.raises(ValueError, match="broken.tle, line 2"):
        read_tle_file(path)


def test_a_name_after_the_lines_is_refused(tmp_path, lines):
    message = "line 3: 'SAMPLE SAT' is not part of a TLE.* name line must come first"
    with pytest.raises(ValueError, match=message):
        read_tle_file(write(tmp_path / "late.tle", [*lines, NAME]))


def test_an_empty_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="holds no TLE"):
        read_tle_file(write(tmp_path / "empty.tle", ["", "  "]))


def test_a_file_may_hold_several_tles_with_or_without_names(group):
    tles = read_tle_sets(group)
    assert [tle.name for tle in tles] == ["RELAY-01", "RELAY-02", None]
    assert [tle.satrec.satnum for tle in tles] == [90001, 90002, 90003]


@pytest.mark.parametrize(
    ("satellite", "number"),
    [("RELAY-01", 90001), ("relay-02", 90002), ("  RELAY-02 ", 90002), (90003, 90003)]
    + [("90001", 90001)],
)
def test_a_satellite_is_picked_by_its_name_or_its_number(group, satellite, number):
    assert read_tle_file(group, satellite).satrec.satnum == number


def test_several_tles_with_none_asked_for_are_refused(group, tmp_path, lines):
    listed = r"RELAY-01 \(90001\), RELAY-02 \(90002\), catalogue number 90003"
    with pytest.raises(ValueError, match=f"holds 3 element sets, .*: {listed}$"):
        read_tle_file(group)
    with pytest.raises(ValueError, match="holds 2 element sets"):
        read_tle_file(write(tmp_path / "two.tle", lines + lines))


def test_a_satellite_that_the_file_does_not_hold_is_refused(group, data_dir):
    with pytest.raises(ValueError, match="no element set named or numbered 'RELAY-09'"):
        read_tle_file(group, "RELAY-09")
    # a file of one TLE must hold the satellite asked for too
    reference = data_dir / "sso_510km.tle"
    assert read_tle_file(reference, 99999).satrec.satnum == 99999
    with pytest.raises(ValueError, match="It holds: catalogue number 99999$"):
        read_tle_file(reference, "RELAY-01")


def test_two_tles_of_one_satellite_are_refused_with_their_epochs(tmp_path, lines):
    history = variant(lines, 90001) + variant(lines, 90001, day="275.00000000")
    path = write(tmp_path / "history.tle", history)
    epochs = "2026-10-01T00:00:00.000 UTC, 2026-10-02T00:00:00.000 UTC"
    with pytest.raises(ValueError, match=f"2 element sets for '90001', .*{epochs}"):
        read_tle_file(path, 90001)


def test_a_long_list_of_names_is_cut(tmp_path, lines):
    path = write(
        tmp_path / "many.tle",
        [line for number in range(12) for line in variant(lines, 90000 + number)],
    )
    with pytest.raises(ValueError, match="catalogue number 90009, and 2 more$"):
        read_tle_file(path, "RELAY-01")


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
    with pytest.warns(UserWarning, match="starts 9.0 days from the epoch of the TLE"):
        text = warn_if_far_from_epoch(tle, Time("2026-10-10T00:00:00", scale="utc"))
    assert text is not None and text.startswith("The run starts 9.0 days")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert (
            warn_if_far_from_epoch(tle, Time("2026-10-06T00:00:00", scale="utc"))
            is None
        )


def test_an_end_far_from_the_epoch_warns_and_names_the_element_set(tle):
    start = Time("2026-10-06T00:00:00", scale="utc")
    end = Time("2026-10-09T00:00:00", scale="utc")
    with pytest.warns(UserWarning, match="ends 8.0 days from the epoch of RELAY-03"):
        warn_if_far_from_epoch(tle, start, end, label="RELAY-03")
    # a run before the epoch counts the same way
    before = Time("2026-09-22T00:00:00", scale="utc")
    with pytest.warns(UserWarning, match="starts 9.0 days"):
        warn_if_far_from_epoch(tle, before, start)
