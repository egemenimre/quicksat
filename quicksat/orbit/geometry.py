# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The sun, the Earth's shadow, where the satellite is over the Earth, and whether two
satellites can see each other.

Everything takes the satellite's state as one `SkyCoord` in GCRS, and works on the whole
array at once. The shadow is two cones cast by the sun's disk on the WGS84 ellipsoid,
after Ortiz Longo and Rickman (1995). `docs/scenario/scenario_ref.ipynb` explains the
shadow, its check against Orekit, and the line of sight.

"""

from collections.abc import Callable
from typing import NamedTuple, cast

import numpy as np
import portion as P
from astropy import constants
from astropy.coordinates import (
    GCRS,
    ITRS,
    CartesianDifferential,
    CartesianRepresentation,
    EarthLocation,
    SkyCoord,
    get_sun,
)
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.utils.intervals import TimeArray, intervals_where

EARTH_EQUATORIAL_RADIUS = Q_(6378.137, "km")
"""Equatorial radius of the WGS84 ellipsoid, which casts the shadow. It is not
`R_EARTH`."""

EARTH_FLATTENING = 1 / 298.257223563
"""Flattening of the WGS84 ellipsoid."""

SUN_RADIUS = constants.R_sun  # pyright: ignore[reportAttributeAccessIssue]
"""Radius of the sun: astropy's default, the IAU 2015 nominal 695 700 km."""

EARTH_ROTATION_RATE = Q_(7.292115e-5, "rad / s")
"""The Earth's rotation rate, the WGS84 value. astropy.constants has none."""


def sun_positions(times: TimeArray) -> CartesianRepresentation:
    """
    Position of the sun relative to the centre of the Earth, in GCRS.

    Parameters
    ----------
    times : Time
        The times, as an array

    Returns
    -------
    sun : CartesianRepresentation
        The apparent position of the sun at each time, in km
    """
    # Explicit casting for pyright
    sun = cast(CartesianRepresentation, get_sun(times).cartesian)
    return CartesianRepresentation(sun.xyz.to(u.km))


def _positions(state: SkyCoord) -> CartesianRepresentation:
    """A state's positions from the Earth's centre, without its velocities."""
    return cast(CartesianRepresentation, state.cartesian).without_differentials()


class _Cones(NamedTuple):
    """Where each position sits against the two shadow cones, in km."""

    along: np.ndarray
    """Distance along the axis, towards the sun. Negative behind the Earth."""

    across: np.ndarray
    """Distance from the axis."""

    stretched: np.ndarray
    """Distance from the axis, with z stretched to make the shadow round."""

    umbra: np.ndarray
    """Radius of the umbra cone at that distance. Negative beyond its tip."""

    penumbra: np.ndarray
    """Radius of the penumbra cone at that distance."""


def _km(vectors: CartesianRepresentation) -> np.ndarray:
    """Cartesian vectors as a plain array in km, of shape (n, 3)."""
    return np.atleast_2d(vectors.xyz.to_value(u.km).T)


def _cones(position: np.ndarray, sun: np.ndarray, flattening: float) -> _Cones:
    """
    Where each position sits against the umbra and the penumbra cones, both touching the
    Earth's equator.
    """
    earth = EARTH_EQUATORIAL_RADIUS.to(u.km).value
    sun_radius = SUN_RADIUS.to(u.km).value
    distance = np.linalg.norm(sun, axis=1)
    axis = sun / distance[:, None]
    along = np.sum(position * axis, axis=1)
    offset = position - along[:, None] * axis
    # stretching z by 1 / (1 - f) makes the ellipsoid's outline round
    stretched = offset * np.array([1.0, 1.0, 1.0 / (1.0 - flattening)])
    # the tips of the cones, measured from the centre of the Earth
    umbra_tip = earth * distance / (sun_radius - earth)
    penumbra_tip = earth * distance / (sun_radius + earth)
    behind = -along
    return _Cones(
        along=along,
        across=np.linalg.norm(offset, axis=1),
        stretched=np.linalg.norm(stretched, axis=1),
        umbra=(umbra_tip - behind) * np.tan(np.arcsin(earth / umbra_tip)),
        penumbra=(penumbra_tip + behind) * np.tan(np.arcsin(earth / penumbra_tip)),
    )


def shadow_cones(
    state: SkyCoord,
    sun: CartesianRepresentation,
    flattening: float = EARTH_FLATTENING,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Whether each position is in the umbra, and whether it is in eclipse. A position on a
    cone's edge is outside it.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS
    sun : CartesianRepresentation
        The sun's positions from the Earth's centre, from `sun_positions`
    flattening : float, optional
        The Earth's flattening, WGS84's by default, 0 for a sphere

    Returns
    -------
    umbra : ndarray
        True where the Earth hides the whole sun
    eclipse : ndarray
        True where the Earth hides some or all of it
    """
    cones = _cones(_km(_positions(state)), _km(sun), flattening)
    behind = cones.along < 0
    return (
        behind & (cones.stretched < cones.umbra),
        behind & (cones.stretched < cones.penumbra),
    )


def light_fraction(
    state: SkyCoord,
    sun: CartesianRepresentation,
    flattening: float = EARTH_FLATTENING,
) -> np.ndarray:
    """
    The share of the sun's disk that the satellite sees, after Montenbruck and Gill,
    section 3.4.2.

    It is exactly 1 outside the eclipse and 0 in the umbra, and agrees with
    `shadow_cones`.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS
    sun : CartesianRepresentation
        The sun's positions from the Earth's centre, from `sun_positions`
    flattening : float, optional
        The Earth's flattening, WGS84's by default, 0 for a sphere

    Returns
    -------
    light : ndarray
        From 0 to 1
    """
    position, sun_km = _km(_positions(state)), _km(sun)
    cones = _cones(position, sun_km, flattening)
    to_sun = sun_km - position
    sun_distance = np.linalg.norm(to_sun, axis=1)
    earth_distance = np.linalg.norm(position, axis=1)
    # the Earth's radius across the axis, in the satellite's direction
    squash = np.divide(
        cones.across,
        cones.stretched,
        out=np.ones_like(cones.across),
        where=cones.stretched > 0,
    )
    earth_radius = EARTH_EQUATORIAL_RADIUS.to(u.km).value * squash
    # apparent radii of the two disks, and the angle between their centres
    a = np.arcsin(SUN_RADIUS.to(u.km).value / sun_distance)
    b = np.arcsin(earth_radius / earth_distance)
    cosine = -np.sum(position * to_sun, axis=1) / (earth_distance * sun_distance)
    c = np.arccos(np.clip(cosine, -1.0, 1.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        x = (c**2 + a**2 - b**2) / (2 * c)
        y = np.sqrt(np.clip(a**2 - x**2, 0.0, None))
        hidden = (
            a**2 * np.arccos(np.clip(x / a, -1.0, 1.0))
            + b**2 * np.arccos(np.clip((c - x) / b, -1.0, 1.0))
            - c * y
        )
    light = 1 - hidden / (np.pi * a**2)
    # where the disks do not cross: apart, the sun hidden, or a ring of sun left
    light = np.where(c >= a + b, 1.0, light)
    light = np.where(c <= b - a, 0.0, light)
    light = np.where(c <= a - b, 1 - (b / a) ** 2, light)
    umbra, eclipse = shadow_cones(state, sun, flattening)
    return np.where(umbra, 0.0, np.where(eclipse, np.clip(light, 0.0, 1.0), 1.0))


def shadow_intervals(
    times: TimeArray,
    flags: tuple[np.ndarray, np.ndarray],
    state_at: Callable[[TimeArray], SkyCoord],
    sun_at: Callable[[TimeArray], CartesianRepresentation] = sun_positions,
    flattening: float = EARTH_FLATTENING,
) -> tuple[P.Interval, P.Interval]:
    """
    The umbra and the eclipses over a time grid, with each edge found to 1 ms between
    the steps.

    Each piece is closed at its entry and open at its exit. A shadow shorter than one
    step can be missed.

    Parameters
    ----------
    times : Time
        The grid's times, in order, rounded with `round_time`
    flags : tuple of ndarray
        The umbra and eclipse flags at each time, from `shadow_cones`
    state_at : callable
        The satellite's state in GCRS for a `Time` array
    sun_at : callable, optional
        The sun's position for a `Time` array, by default `sun_positions`
    flattening : float, optional
        The Earth's flattening, WGS84's by default, 0 for a sphere

    Returns
    -------
    umbra : portion.Interval
        Where the Earth hides the whole sun
    eclipses : portion.Interval
        Where it hides some or all of it, umbra included
    """
    umbra_flags, eclipse_flags = flags

    def umbra_at(at: TimeArray) -> np.ndarray:
        return shadow_cones(state_at(at), sun_at(at), flattening)[0]

    def eclipse_at(at: TimeArray) -> np.ndarray:
        return shadow_cones(state_at(at), sun_at(at), flattening)[1]

    return (
        intervals_where(times, umbra_flags, umbra_at),
        intervals_where(times, eclipse_flags, eclipse_at),
    )


def geodetic(
    state: SkyCoord, earth_at: Callable[[TimeArray], np.ndarray] | None = None
):
    """
    Geodetic latitude and longitude of the point below the satellite, on the WGS84
    ellipsoid.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS
    earth_at : callable, optional
        The Earth's orientation for a `Time` array, as `earth_rotations` gives it. By
        default, astropy turns the positions itself

    Returns
    -------
    latitude : Quantity
        In degrees, from -90 to 90
    longitude : Quantity
        East, in degrees, from -180 to 180
    """
    if earth_at is None:
        positions = state.frame.realize_frame(_positions(state))
        itrs = positions.transform_to(ITRS(obstime=state.obstime))
        geocentric = cast(CartesianRepresentation, itrs.cartesian).xyz
    else:
        earth = earth_at(cast(TimeArray, state.obstime))
        # the rotations turn ITRS vectors into GCRS, so their transposes turn back
        fixed = np.einsum("nji,nj->ni", earth, _km(_positions(state)))
        geocentric = Q_(fixed.T, "km")
    location = EarthLocation.from_geocentric(*geocentric)
    return (
        Q_(np.asarray(location.lat.to_value(u.deg), dtype=float), "deg"),
        Q_(np.asarray(location.lon.to_value(u.deg), dtype=float), "deg"),
    )


def beta_angle(state: SkyCoord, sun: CartesianRepresentation):
    """
    Angle between the sun's direction and the orbit plane, positive on the orbit
    normal's side.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS, with its velocities
    sun : CartesianRepresentation
        The sun's positions from the Earth's centre, from `sun_positions`

    Returns
    -------
    beta : Quantity
        In degrees, from -90 to 90
    """
    cartesian = cast(CartesianRepresentation, state.cartesian)
    velocity = cast(CartesianDifferential, cartesian.differentials["s"])
    normal = cartesian.without_differentials().cross(velocity.to_cartesian())
    normal = normal / normal.norm()
    sine = np.clip(normal.dot(sun / sun.norm()).to_value(u.one), -1, 1)
    return Q_(np.arcsin(sine), "rad").to(u.deg)


def sun_zenith_cosine(state: SkyCoord, sun: CartesianRepresentation) -> np.ndarray:
    """
    The cosine of the sun's zenith angle at the point below the satellite, on a
    spherical Earth.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS
    sun : CartesianRepresentation
        The sun's positions from the Earth's centre, from `sun_positions`

    Returns
    -------
    cosine : ndarray
        1 at the subsolar point, 0 on the terminator, negative at night
    """
    position = cast(CartesianRepresentation, state.cartesian).without_differentials()
    return np.clip(
        (position / position.norm()).dot(sun / sun.norm()).to_value(u.one), -1, 1
    )


def earth_rotations(times: TimeArray) -> np.ndarray:
    """
    The Earth's orientation: the rotations from ITRS into GCRS, as astropy transforms
    the axes.

    Parameters
    ----------
    times : Time
        The times, as an array

    Returns
    -------
    rotations : ndarray
        Shape (n, 3, 3), where column i is ITRS axis i in GCRS
    """
    count = len(times)
    # the three axes at every time, shape (3, n)
    axes = np.broadcast_to(np.eye(3)[:, :, None], (3, 3, count))
    itrs = ITRS(CartesianRepresentation(Q_(axes, "km"), xyz_axis=0), obstime=times)
    gcrs = cast(
        CartesianRepresentation, itrs.transform_to(GCRS(obstime=times)).cartesian
    )
    # xyz has shape (3 components, 3 axes, n): move to (n, components, axes)
    return np.moveaxis(gcrs.xyz.to_value(u.km), -1, 0)


def ground_point(
    latitude: Quantity, longitude: Quantity, altitude: Quantity
) -> np.ndarray:
    """
    A geodetic point's position in ITRS, on the WGS84 ellipsoid.

    Parameters
    ----------
    latitude, longitude : Quantity
        Geodetic latitude, and longitude east
    altitude : Quantity
        Height above the ellipsoid

    Returns
    -------
    position : ndarray
        In km, shape (3,)
    """
    point = EarthLocation.from_geodetic(
        longitude, latitude, float(altitude.to(u.m).value), ellipsoid="WGS84"
    )
    return np.array([coordinate.to_value(u.km) for coordinate in point.geocentric])


def elevations(
    state: SkyCoord,
    latitude: Quantity,
    longitude: Quantity,
    altitude: Quantity,
    earth_at: Callable[[TimeArray], np.ndarray] = earth_rotations,
) -> np.ndarray:
    """
    The satellite's elevation above a ground point's horizon, across the ellipsoid's
    normal.

    Parameters
    ----------
    state : SkyCoord
        The satellite's positions in GCRS, with their times
    latitude, longitude : Quantity
        The point's geodetic latitude, and longitude east
    altitude : Quantity
        The point's height above the ellipsoid
    earth_at : callable, optional
        The Earth's orientation for a `Time` array, by default `earth_rotations`

    Returns
    -------
    elevations : ndarray
        In degrees, from -90 to 90
    """
    earth = earth_at(cast(TimeArray, state.obstime))
    point = earth @ ground_point(latitude, longitude, altitude)
    lat, lon = latitude.to_value(u.rad), longitude.to_value(u.rad)
    normal = np.array(
        [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]
    )
    up = earth @ normal
    line = _km(cast(CartesianRepresentation, state.cartesian)) - point
    sine = np.sum(line * up, axis=1) / np.linalg.norm(line, axis=1)
    return np.degrees(np.arcsin(np.clip(sine, -1, 1)))


def line_of_sight_clear(
    first: SkyCoord,
    second: SkyCoord,
    clearance: Quantity,
    earth_at: Callable[[TimeArray], np.ndarray] = earth_rotations,
) -> np.ndarray:
    """
    Whether the line between two satellites keeps a height above the WGS84 ellipsoid, at
    each time.

    Parameters
    ----------
    first, second : SkyCoord
        The two satellites' positions in GCRS, at `first`'s times
    clearance : Quantity
        The line's least height above the ellipsoid
    earth_at : callable, optional
        The Earth's orientation for a `Time` array, by default `earth_rotations`

    Returns
    -------
    clear : ndarray of bool
        True where each satellite sees the other
    """
    times = cast(TimeArray, first.obstime)
    pole = earth_at(times.ravel()[:1])[0, :, 2]
    height = clearance.to_value(u.km)
    radius = EARTH_EQUATORIAL_RADIUS.to_value(u.km) + height
    polar = EARTH_EQUATORIAL_RADIUS.to_value(u.km) * (1 - EARTH_FLATTENING) + height

    def stretched(state: SkyCoord) -> np.ndarray:
        # stretching along the pole makes the raised ellipsoid a sphere
        position = _km(_positions(state))
        along = position @ pole
        return position + (radius / polar - 1) * along[:, None] * pole

    start, end = stretched(first), stretched(second)
    line = end - start
    length = np.sum(line * line, axis=1)
    # the fraction along the line of its closest point to the centre
    fraction = -np.sum(start * line, axis=1) / np.where(length > 0, length, 1.0)
    closest = start + np.clip(fraction, 0.0, 1.0)[:, None] * line
    return np.linalg.norm(closest, axis=1) >= radius
