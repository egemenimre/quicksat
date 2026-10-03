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
    ITRS,
    CartesianDifferential,
    CartesianRepresentation,
    EarthLocation,
    SkyCoord,
    get_sun,
)

from quicksat import Q_, R_EARTH, u
from quicksat.utils.intervals import TIME_GRID, TimeArray, round_time


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

    Wherever the shadow flag changes between two grid steps, one edge lies
    between them. All the brackets are halved together by bisection. Each
    midpoint evaluates the orbit and the sun again, so the result does not depend
    on the step. The search stops once every bracket is shorter than 1 ms. It then
    takes the midpoint and rounds it with `round_time`.

    It assumes that no bracket holds two edges. That holds for any step far
    shorter than the eclipse. A shadow shorter than one step can be missed.

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
    changed = np.flatnonzero(shadow[:-1] != shadow[1:])
    is_entry = ~shadow[changed]
    epoch = times[0]
    low = (times[changed] - epoch).to_value(u.s)
    high = (times[changed + 1] - epoch).to_value(u.s)
    tolerance = TIME_GRID.to(u.s).value
    while changed.size and (high - low).max() >= tolerance:
        middle = 0.5 * (low + high)
        mid_times = epoch + Q_(middle, "s")
        mid_shadow = in_shadow(state_at(mid_times), sun_at(mid_times))
        # an entry is lit at the low end and dark at the high end, an exit the reverse
        move_high = mid_shadow == is_entry
        high = np.where(move_high, middle, high)
        low = np.where(move_high, low, middle)
    edges = round_time(epoch + Q_(0.5 * (low + high), "s"))

    begins = list(edges[is_entry])
    ends = list(edges[~is_entry])
    if shadow[0]:
        begins.insert(0, times[0])
    if shadow[-1]:
        ends.append(times[-1])
    eclipses = P.empty()
    for begin, end in zip(begins, ends, strict=True):
        eclipses |= P.closedopen(begin, end)
    return eclipses


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
