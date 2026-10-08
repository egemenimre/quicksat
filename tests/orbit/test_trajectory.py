# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for trajectories: the interpolation, the period and the span.

The interpolation is checked against SGP4 itself, as satmad's tests do, for a
low orbit, a geostationary one and a highly eccentric one. The geostationary
and eccentric element sets are satmad's, with an inclination of exactly zero,
so they have no node at all. The period of a circular two-body orbit is known
exactly, which checks both ways of measuring it.
"""

import numpy as np
import pytest
from astropy.coordinates import (
    GCRS,
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.time import Time
from sgp4.api import WGS72, Satrec

from quicksat import MU_EARTH, Q_, u
from quicksat.orbit.tle import Tle
from quicksat.orbit.trajectory import (
    ASCENDING_NODES,
    FIXED_DIRECTION,
    TWO_BODY,
    Trajectory,
)

from .conftest import vectors

GEO_LINES = (
    "1 99999U 12345A   20162.50918981  .00000000  00000-0  00000-0 0 00005",
    "2 99999 000.0000 124.6202 0000000 000.0000 000.0000 01.00273791000004",
)
"""satmad's geostationary element set: circular, with no inclination."""


def checksum(line: str) -> str:
    """A TLE line with its checksum digit written again."""
    total = sum(int(c) if c.isdigit() else c == "-" for c in line[:68])
    return line[:68] + str(total % 10)


@pytest.fixture(scope="module")
def geo() -> Tle:
    """satmad's geostationary orbit."""
    return Tle("GEO", Satrec.twoline2rv(*GEO_LINES, WGS72))


@pytest.fixture(scope="module")  # noqa: V103
def heo() -> Tle:
    """The geostationary orbit with an eccentricity of 0.4, as in satmad."""
    line2 = checksum(GEO_LINES[1].replace(" 0000000 ", " 4000000 "))
    return Tle("HEO", Satrec.twoline2rv(GEO_LINES[0], line2, WGS72))


def sampled(tle: Tle, span_s: float, step_s: float = 60.0) -> Trajectory:
    """A trajectory through SGP4's states, from the epoch on."""
    offsets = np.arange(0, span_s + step_s, step_s)
    return Trajectory.from_states(tle.states(tle.epoch + Q_(offsets, "s")))


def circular(inclination_deg: float, orbits: float, step_s: float = 60.0):
    """A circular two-body orbit at 7000 km, and its exact period."""
    radius = 7000.0
    mu = MU_EARTH.to_value(u.km**3 / u.s**2)
    rate = np.sqrt(mu / radius**3)
    offsets = np.arange(0, orbits * 2 * np.pi / rate, step_s)
    angle = rate * offsets
    i, node = np.radians(inclination_deg), np.radians(40.0)
    # the orbit plane: tilted about x by the inclination, then turned to the node
    turn_x = np.array(
        [[1, 0, 0], [0, np.cos(i), -np.sin(i)], [0, np.sin(i), np.cos(i)]]
    )
    turn_z = np.array(
        [[np.cos(node), -np.sin(node), 0], [np.sin(node), np.cos(node), 0], [0, 0, 1]]
    )
    turn = turn_z @ turn_x
    in_plane = np.stack([np.cos(angle), np.sin(angle), np.zeros_like(angle)])
    along = np.stack([-np.sin(angle), np.cos(angle), np.zeros_like(angle)])
    position = turn @ in_plane * radius
    velocity = turn @ along * radius * rate
    times = Time("2026-10-01T00:00:00", scale="utc") + Q_(offsets, "s")
    data = CartesianRepresentation(Q_(position, "km")).with_differentials(
        CartesianDifferential(Q_(velocity, "km/s"))
    )
    return SkyCoord(GCRS(data, obstime=times)), Q_(2 * np.pi / rate, "s")


# ---------------------------------------------------------------- Interpolation


@pytest.mark.parametrize(
    ("orbit", "span_s", "check_step_s", "inside_mm", "ends_mm", "velocity_mm_s"),
    [
        ("tle", 3 * 5700.0, 1.0, 1.0, 20.0, 0.005),
        ("geo", 3 * 86400.0, 10.0, 0.02, 0.02, 0.02),
        ("heo", 3 * 86400.0, 10.0, 0.2, 0.2, 0.03),
    ],
)
def test_the_interpolation_matches_sgp4(
    request, orbit, span_s, check_step_s, inside_mm, ends_mm, velocity_mm_s
):
    # at 60 s between samples, as satmad's tests have it
    tle = request.getfixturevalue(orbit)
    trajectory = sampled(tle, span_s)
    offsets = np.arange(0, span_s, check_step_s)
    times = tle.epoch + Q_(offsets, "s")
    found, found_velocity = vectors(trajectory.states(times))
    expected, expected_velocity = vectors(tle.states(times))
    position = np.linalg.norm(found - expected, axis=0)
    velocity = np.linalg.norm(found_velocity - expected_velocity, axis=0)
    inside = (offsets > 180) & (offsets < span_s - 180)
    assert position[inside].max() < inside_mm
    assert position.max() < ends_mm
    assert velocity[inside].max() < velocity_mm_s


def test_a_time_outside_the_trajectory_is_refused(tle):
    trajectory = sampled(tle, 600.0)
    with pytest.raises(ValueError, match="outside the trajectory"):
        trajectory.states(tle.epoch + Q_([-1.0, 10.0], "s"))


def test_a_run_must_lie_inside_and_is_warned_near_the_ends(tle):
    trajectory = sampled(tle, 3600.0)
    with pytest.raises(ValueError, match="does not lie inside the trajectory"):
        trajectory.check_covers(tle.epoch - Q_(1, "s"), tle.epoch + Q_(600, "s"))
    with pytest.warns(UserWarning, match="within 3 samples"):
        trajectory.check_covers(tle.epoch + Q_(60, "s"), tle.epoch + Q_(1800, "s"))
    trajectory.check_covers(tle.epoch + Q_(600, "s"), tle.epoch + Q_(1800, "s"))


def test_too_few_samples_or_falling_times_are_refused(tle):
    state = tle.states(tle.epoch + Q_(np.arange(5) * 60.0, "s"))
    with pytest.raises(ValueError, match="at least 6 samples"):
        Trajectory.from_states(state)
    zeros = np.zeros((6, 3))
    with pytest.raises(ValueError, match="must rise"):
        Trajectory(tle.epoch, np.array([0, 60, 60, 120, 180, 240]), zeros, zeros)


# ---------------------------------------------------------------- The period


def test_the_period_of_an_inclined_orbit_is_its_nodal_period(tle):
    trajectory = sampled(tle, 5 * 5700.0)
    assert trajectory.period_method == ASCENDING_NODES
    assert trajectory.period.to_value(u.s) == pytest.approx(
        tle.nodal_period.to_value(u.s), abs=5e-3
    )


def test_a_geostationary_period_is_measured_against_a_fixed_direction(geo):
    # with no inclination there is no node, and SGP4's mean rate of the true
    # longitude is the nearest thing to compare with
    trajectory = sampled(geo, 3 * 86400.0)
    satrec = geo.satrec
    rate = satrec.mdot + satrec.argpdot + satrec.nodedot  # rad/min
    assert trajectory.period_method == FIXED_DIRECTION
    assert trajectory.period.to_value(u.s) == pytest.approx(
        2 * np.pi / rate * 60, abs=3.0
    )


@pytest.mark.parametrize(
    ("inclination", "method"),
    [
        (0.0, FIXED_DIRECTION),
        (0.5, FIXED_DIRECTION),
        (30.0, ASCENDING_NODES),
        (98.0, ASCENDING_NODES),
    ],
)
def test_both_ways_find_the_two_body_period(inclination, method):
    state, period = circular(inclination, orbits=3)
    trajectory = Trajectory.from_states(state)
    assert trajectory.period_method == method
    assert trajectory.period_measured
    assert trajectory.period.to_value(u.s) == pytest.approx(
        period.to_value(u.s), abs=1e-3
    )


def test_a_trajectory_shorter_than_an_orbit_estimates_its_period():
    state, period = circular(30.0, orbits=0.8)
    trajectory = Trajectory.from_states(state)
    assert trajectory.period_method == TWO_BODY
    assert not trajectory.period_measured
    assert trajectory.period.to_value(u.s) == pytest.approx(
        period.to_value(u.s), rel=1e-9
    )
