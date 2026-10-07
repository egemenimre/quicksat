# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the geometry: the beta angle, the shadow, and the Earth.

For the beta angle, the satellite sits on the x axis and moves along y, so the
orbit normal is +z. For the shadow, the sun lies along +x. Both are placed by
hand, so the expected results follow from the geometry alone. The umbra and the
penumbra over a day are checked against Orekit, on a sphere and on WGS84.
"""

import json
from typing import cast

import numpy as np
import pytest
from astropy.coordinates import (
    GCRS,
    ITRS,
    CartesianDifferential,
    CartesianRepresentation,
    EarthLocation,
    SkyCoord,
)
from astropy.tests.helper import assert_quantity_allclose
from astropy.time import Time

from quicksat import Q_, u
from quicksat.orbit.geometry import (
    EARTH_EQUATORIAL_RADIUS,
    EARTH_FLATTENING,
    SUN_RADIUS,
    beta_angle,
    earth_rotations,
    geodetic,
    light_fraction,
    shadow_cones,
    shadow_intervals,
    sun_positions,
)
from quicksat.orbit.tle import tle_states
from quicksat.utils.intervals import round_time


@pytest.fixture
def state():
    position = CartesianRepresentation([6878.0, 0.0, 0.0], unit=u.km)
    velocity = CartesianDifferential([0.0, 7.6, 0.0], unit=u.km / u.s)
    obstime = Time("2026-01-01T00:00:00", scale="utc")
    return SkyCoord(position.with_differentials(velocity), frame=GCRS(obstime=obstime))


def sun_at(elevation_deg):
    """The sun 1 au away, at this angle above the orbit plane, toward +x."""
    angle = np.radians(elevation_deg)
    return CartesianRepresentation([np.cos(angle), 0.0, np.sin(angle)], unit=u.au)


@pytest.mark.parametrize("elevation", [90.0, 45.0, 0.0, -30.0, -90.0])
def test_beta_is_the_sun_elevation_above_the_orbit_plane(state, elevation):
    assert_quantity_allclose(
        beta_angle(state, sun_at(elevation)), Q_(elevation, "deg"), atol=Q_(1e-9, "deg")
    )


def test_beta_ignores_where_the_sun_is_along_the_plane(state):
    # Rotating the sun about the orbit normal does not change beta
    sun = CartesianRepresentation([0.0, -np.cos(0.5), np.sin(0.5)], unit=u.au)
    assert_quantity_allclose(
        beta_angle(state, sun), Q_(0.5, "rad"), atol=Q_(1e-9, "deg")
    )


def test_beta_flips_sign_with_the_direction_of_motion(state):
    reverse = CartesianDifferential([0.0, -7.6, 0.0], unit=u.km / u.s)
    retrograde = SkyCoord(
        state.cartesian.without_differentials().with_differentials(reverse),
        frame=state.frame.replicate_without_data(),
    )
    assert_quantity_allclose(
        beta_angle(retrograde, sun_at(45.0)), Q_(-45.0, "deg"), atol=Q_(1e-9, "deg")
    )


# ---------------------------------------------------------------- The shadow


def satellites_at(*positions):
    """Satellites at positions in GCRS, in km, without velocities."""
    obstime = Time("2026-01-01T00:00:00", scale="utc")
    xyz = np.array(positions, dtype=float).T
    return SkyCoord(
        CartesianRepresentation(xyz, unit=u.km), frame=GCRS(obstime=obstime)
    )


def sun_along_x(count):
    """The sun, 1 au along +x, once for each satellite."""
    return CartesianRepresentation(np.tile([[1.0], [0.0], [0.0]], count), unit=u.au)


# 7000 km behind the Earth, the umbra cone's radius is 6345.95 km and the
# penumbra cone's 6411.06 km
BEHIND = -7000.0


@pytest.mark.parametrize(
    ("position", "umbra", "eclipse"),
    [
        ((BEHIND, 0.0, 0.0), True, True),  # on the axis
        ((BEHIND, 6300.0, 0.0), True, True),  # inside the umbra cone
        ((BEHIND, 6380.0, 0.0), False, True),  # between the two cones
        ((BEHIND, 6500.0, 0.0), False, False),  # outside the penumbra cone
        ((7000.0, 0.0, 0.0), False, False),  # on the sun's side
        ((0.0, 7000.0, 0.0), False, False),  # beside the Earth
    ],
)
def test_shadow_cones(position, umbra, eclipse):
    in_umbra, in_eclipse = shadow_cones(satellites_at(position), sun_along_x(1))
    assert bool(in_umbra[0]) is umbra
    assert bool(in_eclipse[0]) is eclipse


def test_the_flattening_shrinks_the_shadow_towards_the_poles():
    # 6340 km off the axis towards the pole: inside a sphere's umbra cone, but the
    # flattened Earth is shorter there, which leaves the point in penumbra
    above_the_pole = satellites_at((BEHIND, 0.0, 6340.0))
    sphere = shadow_cones(above_the_pole, sun_along_x(1), flattening=0.0)
    wgs84 = shadow_cones(above_the_pole, sun_along_x(1))
    assert (bool(sphere[0][0]), bool(sphere[1][0])) == (True, True)
    assert (bool(wgs84[0][0]), bool(wgs84[1][0])) == (False, True)


@pytest.mark.parametrize("flattening", [0.0, EARTH_FLATTENING])
def test_the_light_falls_smoothly_across_the_penumbra(flattening):
    across = np.arange(6250.0, 6500.0, 0.1)
    satellites = satellites_at(*[(BEHIND, y, 0.0) for y in across])
    light = light_fraction(satellites, sun_along_x(len(across)), flattening)
    umbra, eclipse = shadow_cones(satellites, sun_along_x(len(across)), flattening)
    assert np.all(light[umbra] == 0)
    assert np.all(light[~eclipse] == 1)
    penumbra = eclipse & ~umbra
    assert np.all((light[penumbra] > 0) & (light[penumbra] < 1))
    # the light only grows away from the axis, with no step at either edge
    steps = np.diff(light)
    assert np.all(steps >= 0)
    assert steps.max() < 0.01


def test_beyond_the_tip_of_the_umbra_a_ring_of_sun_is_left():
    # 3 million km behind the Earth, its disk looks smaller than the sun's
    far = satellites_at((-3.0e6, 0.0, 0.0))
    umbra, eclipse = shadow_cones(far, sun_along_x(1), flattening=0.0)
    assert (bool(umbra[0]), bool(eclipse[0])) == (False, True)
    sun_km = SUN_RADIUS.to(u.km).value
    earth_km = EARTH_EQUATORIAL_RADIUS.to(u.km).value
    sun_angle = np.arcsin(sun_km / (u.au.to(u.km) + 3.0e6))
    earth_angle = np.arcsin(earth_km / 3.0e6)
    expected = 1 - (earth_angle / sun_angle) ** 2
    light = light_fraction(far, sun_along_x(1), flattening=0.0)
    assert light[0] == pytest.approx(expected, rel=1e-9)


@pytest.fixture(scope="module")
def reference_day(tle, data_dir):
    """Orekit's eclipse times, and the reference orbit over the same day."""
    reference = json.loads((data_dir / "eclipse_orekit.json").read_text())
    epoch = round_time(Time(reference["epoch_utc"].rstrip("Z"), scale="utc"))
    times = round_time(epoch + np.arange(0, reference["duration_s"] + 1, 10.0) * u.s)

    def positions_at(at):
        return tle_states(tle, at, with_velocity=False)

    return reference, epoch, times, positions_at


@pytest.mark.parametrize(
    ("model", "flattening"),
    [("sphere", 0.0), ("wgs84", EARTH_FLATTENING)],
)
def test_umbra_and_penumbra_match_orekit_over_a_day(reference_day, model, flattening):
    # The tolerances are those of tests/power/data/README.md. All the edges share
    # about 0.05 s from the aberration in astropy's apparent sun.
    reference, epoch, times, positions_at = reference_day
    flags = shadow_cones(positions_at(times), sun_positions(times), flattening)
    umbra, eclipses = shadow_intervals(
        times, flags, positions_at, flattening=flattening
    )
    for found, cone in ((umbra, "umbra"), (eclipses, "penumbra")):
        orekit = reference["models"][f"{model}_{cone}"]
        entries = np.array([(piece.lower - epoch).to_value(u.s) for piece in found])
        exits = np.array([(piece.upper - epoch).to_value(u.s) for piece in found])
        assert len(entries) == len(orekit["entry_s"])
        assert np.max(np.abs(entries - orekit["entry_s"])) < 0.15
        assert np.max(np.abs(exits - orekit["exit_s"])) < 0.15
        durations = np.subtract(orekit["exit_s"], orekit["entry_s"])
        assert np.max(np.abs((exits - entries) - durations)) < 0.10


# ---------------------------------------------------------------- The Earth


def test_geodetic_gives_back_a_known_place():
    obstime = Time("2026-10-01T00:00:00", scale="utc")
    place = EarthLocation.from_geodetic(30 * u.deg, 45 * u.deg, 500 * u.km)
    state = SkyCoord(place.get_gcrs(obstime))
    latitude, longitude = geodetic(state)
    assert_quantity_allclose(latitude, Q_(45, "deg"), atol=Q_(1e-6, "deg"))
    assert_quantity_allclose(longitude, Q_(30, "deg"), atol=Q_(1e-6, "deg"))


def test_earth_rotations_turn_itrs_into_gcrs():
    times = Time("2026-10-01T00:00:00", scale="utc") + np.arange(5) * u.h
    rotations = earth_rotations(times)
    assert np.allclose(rotations @ np.transpose(rotations, (0, 2, 1)), np.eye(3))
    vector = np.array([1234.5, -5678.9, 4321.0])
    itrs = ITRS(
        CartesianRepresentation(*(vector[:, None] * np.ones(5)), unit=u.km),
        obstime=times,
    )
    gcrs = cast(
        CartesianRepresentation, itrs.transform_to(GCRS(obstime=times)).cartesian
    )
    expected = gcrs.xyz.to_value(u.km).T
    assert np.allclose(rotations @ vector, expected, atol=1e-9)
