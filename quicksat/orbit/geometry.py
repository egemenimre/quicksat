# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The sun, the Earth's shadow, and where the satellite is over the Earth.

Everything here takes the satellite's state as one astropy `SkyCoord` in GCRS,
as `tle_states` gives it. The state carries the positions, the velocities when
they are needed, and the times. Everything works on the whole array at once.

The sun's position comes from astropy's `get_sun`: the apparent sun seen from the
centre of the Earth, with its distance. The beta angle takes the direction from
the centre of the Earth, because that is how beta is defined. The satellite's own
velocity shifts where it sees the sun, by about 5 arcsec in low orbit. That
changes where it would point, not whether the Earth blocks the light, so it is
left out.

The shadow is cast by the sun's disk on the WGS84 ellipsoid. It is two cones on
the line from the centre of the Earth to the sun, after Ortiz Longo and Rickman,
NASA Technical Paper 3547 (1995). Inside the umbra cone, the Earth hides the
whole sun. Between the umbra and the penumbra cones, it hides part of the sun.
The eclipse is the penumbra cone, so it holds the umbra too. The flattening is
applied by stretching the satellite's offset from the axis along z, which turns
the ellipsoid's shadow into a circle. Against Orekit's shadow on the WGS84
ellipsoid, the eclipse edges agree to 0.07 s over a day of a 510 km orbit.

The cones hold up to the tip of the umbra cone, about 1.38 million km behind the
Earth. Beyond it lies the antumbra, where the sun shows as a ring around the
Earth. There, the satellite counts as in penumbra, and `light_fraction` gives
the light of the ring. The atmosphere is left out, and so is the Moon's shadow.

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

from quicksat import Q_, u
from quicksat.utils.intervals import TimeArray, intervals_where

EARTH_EQUATORIAL_RADIUS = Q_(6378.137, "km")
"""Equatorial radius of the WGS84 ellipsoid, the shape that casts the shadow.

astropy.constants has no WGS84 values. Its `R_earth` is the IAU 2015 nominal
6378.1 km, which is `R_EARTH`.
"""

EARTH_FLATTENING = 1 / 298.257223563
"""Flattening of the WGS84 ellipsoid."""

SUN_RADIUS = constants.R_sun  # pyright: ignore[reportAttributeAccessIssue]
"""Radius of the sun: astropy's default, the IAU 2015 nominal 695 700 km."""


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
    """
    The positions of a state, without its velocities.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS

    Returns
    -------
    position : CartesianRepresentation
        Positions relative to the centre of the Earth
    """
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
    """
    Cartesian vectors as a plain array in km, one row each.

    Parameters
    ----------
    vectors : CartesianRepresentation
        One vector or an array of them

    Returns
    -------
    km : ndarray
        Shape (n, 3)
    """
    return np.atleast_2d(vectors.xyz.to_value(u.km).T)


def _cones(position: np.ndarray, sun: np.ndarray, flattening: float) -> _Cones:
    """
    Where each position sits against the umbra and penumbra cones.

    The umbra cone narrows behind the Earth to a tip, where the Earth and the sun
    look the same size. The penumbra cone widens behind the Earth from a tip
    between the Earth and the sun. Both touch the Earth's equator.

    Parameters
    ----------
    position : ndarray
        Positions relative to the centre of the Earth in GCRS, shape (n, 3) [km]
    sun : ndarray
        Positions of the sun relative to the centre of the Earth, shape (n, 3) [km]
    flattening : float
        Flattening of the Earth. 0 for a sphere.

    Returns
    -------
    cones : _Cones
        The distances along and across the axis, and the radii of the cones there
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
    Whether each position is in the umbra, and whether it is in eclipse.

    A position on the sun's side of the Earth is sunlit. Behind the Earth, it is
    in the umbra inside the umbra cone, and in eclipse inside the penumbra cone.
    A position exactly on the edge of a cone counts as outside it.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS. Only its positions are used.
    sun : CartesianRepresentation
        Positions of the sun relative to the centre of the Earth, as from
        `sun_positions`
    flattening : float, optional
        Flattening of the Earth. WGS84 by default, and 0 for a sphere.

    Returns
    -------
    umbra : ndarray
        True where the Earth hides the whole sun, as an array of bools
    eclipse : ndarray
        True where the Earth hides some or all of the sun
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
    The fraction of the sun's disk that the satellite sees.

    The overlap of the sun's disk and the Earth's disk, as seen from the
    satellite, follows Montenbruck and Gill, *Satellite Orbits*, section 3.4.2.
    The Earth's apparent radius is taken along the satellite's direction on the
    ellipsoid, so that the fraction agrees with the cones of `shadow_cones`. It
    is exactly 1 outside the eclipse and 0 in the umbra.

    Beyond the tip of the umbra cone, the Earth's disk lies inside the sun's, and
    the light left is the ring around it.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS. Only its positions are used.
    sun : CartesianRepresentation
        Positions of the sun relative to the centre of the Earth, as from
        `sun_positions`
    flattening : float, optional
        Flattening of the Earth. WGS84 by default, and 0 for a sphere.

    Returns
    -------
    light : ndarray
        The fraction of the sun seen, from 0 to 1
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
    The umbra and the eclipses over the span of a time grid, as portion intervals.

    `intervals_where` locates each shadow edge between the grid steps, to 1 ms.
    Each midpoint of its search evaluates the orbit and the sun again, so the
    result does not depend on the step. A shadow shorter than one step can be
    missed.

    Each piece is closed at its entry and open at its exit. A piece already under
    way at the first time begins there, and one still under way at the last time
    ends there. These cut ends are not entries or exits. `next_start` never takes
    them for one.

    Parameters
    ----------
    times : Time
        The grid times, in order, rounded with `round_time`
    flags : tuple of ndarray
        The umbra and eclipse flags at each grid time, from `shadow_cones` with
        the same flattening
    state_at : callable
        Gives the satellite's state in GCRS for a `Time` array. Positions alone
        are enough.
    sun_at : callable, optional
        Gives the position of the sun in GCRS for a `Time` array.
        `sun_positions` by default.
    flattening : float, optional
        Flattening of the Earth. WGS84 by default, and 0 for a sphere.

    Returns
    -------
    umbra : portion.Interval
        Where the Earth hides the whole sun
    eclipses : portion.Interval
        Where the Earth hides some or all of the sun. It holds the umbra.
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


def geodetic(state: SkyCoord):
    """
    Geodetic latitude and longitude of the point below the satellite.

    The positions go through ITRS, the Earth-fixed frame. The velocities are left
    behind, because astropy transforms them about five times slower and the
    latitude does not need them. astropy's `EarthLocation` then gives latitude
    and longitude on the WGS84 ellipsoid. The latitude is geodetic, as on a map.
    It differs from the geocentric latitude by up to 0.19 degrees.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS

    Returns
    -------
    latitude : Quantity
        Geodetic latitude, in degrees from -90 to 90
    longitude : Quantity
        East longitude, in degrees from -180 to 180
    """
    positions = state.frame.realize_frame(_positions(state))
    itrs = positions.transform_to(ITRS(obstime=state.obstime))
    geocentric = cast(CartesianRepresentation, itrs.cartesian)
    location = EarthLocation.from_geocentric(*geocentric.xyz)
    return (
        Q_(np.asarray(location.lat.to_value(u.deg), dtype=float), "deg"),
        Q_(np.asarray(location.lon.to_value(u.deg), dtype=float), "deg"),
    )


def beta_angle(state: SkyCoord, sun: CartesianRepresentation):
    """
    Angle between the sun direction and the orbit plane.

    It is positive when the sun is on the same side of the orbit plane as the
    orbit normal. The orbit normal is the position crossed with the velocity.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS, with its velocities
    sun : CartesianRepresentation
        Positions of the sun relative to the centre of the Earth, as from
        `sun_positions`. Beta takes the direction from the centre of the Earth.

    Returns
    -------
    beta : Quantity
        The beta angle at each time, in degrees from -90 to 90
    """
    cartesian = cast(CartesianRepresentation, state.cartesian)
    velocity = cast(CartesianDifferential, cartesian.differentials["s"])
    normal = cartesian.without_differentials().cross(velocity.to_cartesian())
    normal = normal / normal.norm()
    sine = np.clip(normal.dot(sun / sun.norm()).to_value(u.one), -1, 1)
    return Q_(np.arcsin(sine), "rad").to(u.deg)


def earth_rotations(times: TimeArray) -> np.ndarray:
    """
    The orientation of the Earth: rotations from ITRS, fixed to the Earth, into
    GCRS.

    The three axes of ITRS are each transformed into GCRS by astropy. That
    includes the Earth's turn, precession, nutation and polar motion. Both frames
    are centred on the Earth, so the transform is a pure rotation.

    Parameters
    ----------
    times : Time
        The times, as an array

    Returns
    -------
    rotations : ndarray
        Matrices that turn ITRS vectors into GCRS, shape (n, 3, 3). Column i is
        ITRS axis i, seen in GCRS.
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
