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

from typing import cast

import numpy as np
import pytest
from astropy.coordinates import (
    GCRS,
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.time import Time
from scipy.spatial.transform import Rotation
from sgp4.api import WGS72, Satrec

from quicksat import MU_EARTH, Q_, u
from quicksat.orbit.tle import Tle
from quicksat.orbit.trajectory import (
    ASCENDING_NODES,
    FIXED_DIRECTION,
    TWO_BODY,
    Trajectory,
)
from quicksat.utils.intervals import TimeArray

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


START = Time("2026-10-01T00:00:00", scale="utc")
"""The start of the circular orbits."""


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
    times = START + Q_(offsets, "s")
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


def test_few_samples_lower_the_degree_and_one_or_falling_times_are_refused(tle):
    state = tle.states(tle.epoch + Q_(np.arange(5) * 60.0, "s"))
    with pytest.warns(UserWarning, match="degree 4 instead of 5"):
        Trajectory.from_states(state)
    with pytest.raises(ValueError, match="at least 2 samples"):
        Trajectory.from_states(tle.states(tle.epoch + Q_([0.0], "s")))
    zeros = np.zeros((6, 3))
    with pytest.raises(ValueError, match="must rise"):
        Trajectory(tle.epoch, [(np.array([0, 60, 60, 120, 180, 240.0]), zeros, zeros)])


# ---------------------------------------------------------------- Segments


def times_of(state: SkyCoord) -> TimeArray:
    """The times of a state, typed for the checker."""
    return state.obstime


def part(state: SkyCoord, index) -> SkyCoord:
    """Some of a state's samples, typed for the checker."""
    return cast(SkyCoord, state[index])


def pieces(state: SkyCoord, *bounds: tuple[float, float]) -> list[SkyCoord]:
    """The states between each pair of bounds, in seconds from the first."""
    times = times_of(state)
    # rounded, since a time difference of 3000 s comes out as 2999.999...
    offsets = np.round((times - times[0]).to_value(u.s), 6)
    return [part(state, (offsets >= low) & (offsets <= high)) for low, high in bounds]


BURN_S = 3000.0
"""When the plane of the orbit turns, in seconds from its start."""


def gcrs(times, position: np.ndarray, velocity: np.ndarray) -> SkyCoord:
    """States in GCRS from positions [mm] and velocities [mm/s], shape (3, n)."""
    data = CartesianRepresentation(Q_(position, "mm")).with_differentials(
        CartesianDifferential(Q_(velocity, "mm/s"))
    )
    return SkyCoord(GCRS(data, obstime=times))


def burn(state: SkyCoord, angle_deg: float = 1.0) -> SkyCoord:
    """
    The states after a burn at `BURN_S` from `START` that turns the plane by an
    angle: each turned about the position at the burn, which the turn leaves in
    place. The states must include the burn.
    """
    offsets = (times_of(state) - START).to_value(u.s)
    position, velocity = vectors(state)
    at_burn = position[:, np.argmin(np.abs(offsets - BURN_S))]
    turn = Rotation.from_rotvec(
        np.radians(angle_deg) * at_burn / np.linalg.norm(at_burn)
    ).as_matrix()
    return gcrs(times_of(state), turn @ position, turn @ velocity)


def test_segments_keep_a_manoeuvre_that_one_spline_smooths():
    coarse, _ = circular(51.6, orbits=1.2)
    fine, _ = circular(51.6, orbits=1.2, step_s=1.0)
    before, after = pieces(coarse, (0, BURN_S), (BURN_S, 1e9))
    turned = burn(after)
    segmented = Trajectory.from_segments([before, turned])
    # one spline through the same samples, with the burn's sample once
    joined = Trajectory.from_states(
        gcrs(
            times_of(coarse),
            np.concatenate([vectors(before)[0][:, :-1], vectors(turned)[0]], axis=1),
            np.concatenate([vectors(before)[1][:, :-1], vectors(turned)[1]], axis=1),
        )
    )
    times = times_of(fine)
    offsets = (times - times[0]).to_value(u.s)
    near = np.abs(offsets - BURN_S) < 300
    exact = np.where(
        offsets[near] < BURN_S,
        vectors(part(fine, near))[0],
        vectors(part(burn(fine), near))[0],
    )
    errors = {
        name: np.linalg.norm(vectors(trajectory.states(times[near]))[0] - exact, axis=0)
        for name, trajectory in (("segmented", segmented), ("joined", joined))
    }
    assert errors["segmented"].max() < 20.0  # mm
    assert errors["joined"].max() > 10_000.0  # mm


def test_where_two_segments_meet_the_later_one_applies():
    coarse, _ = circular(51.6, orbits=1.2)
    before, after = pieces(coarse, (0, BURN_S), (BURN_S, 1e9))
    turned = burn(after)
    trajectory = Trajectory.from_segments([before, turned])
    at_burn = times_of(coarse)[0] + Q_(BURN_S, "s")
    _, velocity = vectors(trajectory.states(at_burn + Q_([-1e-3, 0.0], "s")))
    _, expected_before = vectors(part(before, slice(-1, None)))
    _, expected_after = vectors(part(turned, slice(0, 1)))
    assert np.allclose(velocity[:, 1], expected_after[:, 0], atol=1e-3)
    assert np.allclose(velocity[:, 0], expected_before[:, 0], atol=10.0)
    assert trajectory.segment_count == 2


def test_a_run_may_not_cross_a_gap_between_segments():
    state, _ = circular(51.6, orbits=1.2)
    trajectory = Trajectory.from_segments(pieces(state, (0, 1800), (3600, 5400)))
    start = times_of(state)[0]
    trajectory.check_covers(start + Q_(600, "s"), start + Q_(1200, "s"))
    with pytest.raises(ValueError, match="crosses a gap .* between segments 1 and 2"):
        trajectory.check_covers(start + Q_(600, "s"), start + Q_(4000, "s"))
    with pytest.raises(ValueError, match="outside the trajectory.*with gaps"):
        trajectory.states(start + Q_([2700.0], "s"))


def test_a_segment_serves_its_span_and_segments_may_not_overlap():
    state, _ = circular(51.6, orbits=0.5)
    start = times_of(state)[0]
    span = (start + Q_(300, "s"), start + Q_(1500, "s"))
    trajectory = Trajectory.from_segments(pieces(state, (0, 1800)), [span])
    assert trajectory.start == span[0]
    with pytest.raises(ValueError, match="outside the trajectory"):
        trajectory.states(start + Q_([200.0], "s"))
    with pytest.raises(ValueError, match="segment 2 overlaps"):
        Trajectory.from_segments(pieces(state, (0, 1200), (600, 1800)))


def test_the_period_counts_the_crossings_of_every_segment():
    state, period = circular(51.6, orbits=3)
    trajectory = Trajectory.from_segments(pieces(state, (0, 9000), (9000, 1e9)))
    assert trajectory.period_method == ASCENDING_NODES
    assert trajectory.period.to_value(u.s) == pytest.approx(
        period.to_value(u.s), abs=1e-3
    )


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
