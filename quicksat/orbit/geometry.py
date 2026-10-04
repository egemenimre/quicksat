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
centre of the Earth, with its distance. The shadow test uses the line from the
satellite to that position, not the direction from the centre of the Earth. The
two differ by up to the satellite's distance over the sun's: 9.5 arcsec at 500 km,
and 58 arcsec in a geostationary orbit. The beta angle keeps the direction from
the centre of the Earth, because that is how beta is defined.

The satellite's own velocity shifts where it sees the sun, by about 5 arcsec in
low orbit. That changes where it would point, not whether the Earth blocks the
light, so it is left out.

The shadow is cast by a point sun on a spherical Earth of radius `R_EARTH`. So a
satellite is either sunlit or in eclipse, and there is no penumbra. The edge of
this shadow falls in the middle of the real penumbra.

"""

from collections.abc import Callable
from typing import cast

import numpy as np
import portion as P
from astropy.coordinates import (
    GCRS,
    ITRS,
    CartesianDifferential,
    CartesianRepresentation,
    EarthLocation,
    SkyCoord,
    get_sun,
)

from quicksat import Q_, R_EARTH, u
from quicksat.utils.intervals import TimeArray, intervals_where


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


def in_shadow(state: SkyCoord, sun: CartesianRepresentation):
    """
    Whether each position is in the Earth's shadow, cast by a point sun.

    Light from the centre of the sun reaches the satellite along a straight line.
    The satellite is in eclipse when that line, followed from the satellite
    towards the sun, passes the centre of the Earth closer than `R_EARTH`. A
    position exactly on the edge counts as sunlit.

    Parameters
    ----------
    state : SkyCoord
        The satellite's state in GCRS. Only its positions are used.
    sun : CartesianRepresentation
        Positions of the sun relative to the centre of the Earth, as from
        `sun_positions`

    Returns
    -------
    shadow : ndarray
        True where the position is in eclipse, as an array of bools
    """
    position = _positions(state)
    towards_sun = sun - position
    towards_sun = towards_sun / towards_sun.norm()
    along = position.dot(towards_sun)
    perpendicular = (position - along * towards_sun).norm()
    return (along < Q_(0, "km")) & (perpendicular < R_EARTH)


def eclipse_intervals(
    times: TimeArray,
    shadow: np.ndarray,
    state_at: Callable[[TimeArray], SkyCoord],
    sun_at: Callable[[TimeArray], CartesianRepresentation] = sun_positions,
) -> P.Interval:
    """
    The eclipses over the span of a time grid, as portion intervals.

    `intervals_where` locates each shadow edge between the grid steps, to 1 ms.
    Each midpoint of its search evaluates the orbit and the sun again, so the
    result does not depend on the step. A shadow shorter than one step can be
    missed.

    Each eclipse is closed at its entry and open at its exit. An eclipse already
    under way at the first time begins there, and one still under way at the last
    time ends there. These cut ends are not entries or exits. `next_start`
    never takes them for one.

    Parameters
    ----------
    times : Time
        The grid times, in order, rounded with `round_time`
    shadow : ndarray
        The shadow flag at each grid time, from `in_shadow`
    state_at : callable
        Gives the satellite's state in GCRS for a `Time` array. Positions alone
        are enough.
    sun_at : callable, optional
        Gives the position of the sun in GCRS for a `Time` array.
        `sun_positions` by default.

    Returns
    -------
    eclipses : portion.Interval
        The eclipses, between the first and the last time of the grid
    """

    def shadow_at(at: TimeArray) -> np.ndarray:
        return in_shadow(state_at(at), sun_at(at))

    return intervals_where(times, shadow, shadow_at)


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
