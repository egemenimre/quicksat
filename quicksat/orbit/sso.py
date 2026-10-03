# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Sun-synchronous orbits, built as a TLE that SGP4 reads as asked.

A TLE holds SGP4's own mean elements. So each element is set against SGP4
itself, not against a textbook formula:

- The inclination makes SGP4's secular node rate match the mean sun, 360 degrees
  in 365.2421897 days. SGP4 works this rate out from J2, J2 squared and J4, with
  WGS72 constants. A formula from another theory reads the elements differently.
  At 510 km it misses by about 0.01 degrees, which lets the local time of the
  node drift by minutes a year.
- The mean motion makes the altitude, averaged over one orbit, match the one asked
  for. The altitude is the distance from the centre of the Earth minus `R_EARTH`,
  as in the sizing domain's `Mission`.
- The right ascension of the node puts it at the asked local mean time at the
  epoch.

The inclination and the mean motion depend on each other a little, so they are
found in turn until the altitude settles. The orbit is circular. At the epoch,
the satellite is at the ascending node of the mean orbit. SGP4's short-period
terms move its actual position a little, about 0.1 degrees of latitude at 510 km.

"""

import numpy as np
from astropy.units import Quantity
from sgp4.api import SGP4_ERRORS, WGS72, Satrec

from quicksat import MU_EARTH, Q_, R_EARTH, u
from quicksat.orbit.tle import Tle, nodal_period
from quicksat.utils.intervals import TimeArray

MEAN_SUN_RATE = Q_(360 / 365.2421897, "deg / day")
"""Rate of the mean sun: one turn per tropical year (Vallado, 4th edition, p. 863)."""

SATELLITE_NUMBER = 99999
"""Catalogue number written into a built TLE. It names no real satellite."""

_SGP4_EPOCH_ZERO = 2433281.5
"""Julian date of 1949-12-31 00:00 UTC, which `sgp4init` counts its epoch from."""

_SAMPLES_PER_ORBIT = 720
"""Number of points the altitude is averaged over, spread evenly over one orbit."""

_ALTITUDE_TOLERANCE = Q_(1, "mm")
"""How close the averaged altitude must come to the one asked for."""

_MAX_ITERATIONS = 20
"""Most rounds of inclination and mean motion before the search gives up."""

_INCLINATION_LOW = float(np.radians(90.0))
"""Lower end of the search for the sun-synchronous inclination, 90 degrees [rad].

The node rate is zero at 90 degrees, and grows towards 180 degrees. sgp4 takes
plain radians, so the two ends are plain numbers.
"""

_INCLINATION_HIGH = float(np.radians(179.9))
"""Upper end of the search, 179.9 degrees [rad]. It stops short of 180 degrees,
where SGP4 divides by one plus the cosine of the inclination."""

_BISECTIONS = 60
"""Halvings of the inclination range, well past the precision of a float."""


def sso_tle(
    epoch: TimeArray, altitude: Quantity, ltan: Quantity, name: str | None = None
) -> Tle:
    """
    A TLE for a circular sun-synchronous orbit.

    SGP4 reads the TLE as the orbit asked for. Its secular node rate matches the
    mean sun, and its altitude, averaged over one orbit, is `altitude`. The
    ascending node is at the local mean time `ltan` at the epoch. The satellite
    is at the node of the mean orbit then.

    The element set keeps its full precision. Written out as TLE lines, with
    `Tle.lines`, the inclination and the right ascension round to 0.0001 degrees.
    Read back, those lines drift the local time of the node by under 0.02 min a
    year, and move it by under 0.03 s.

    Parameters
    ----------
    epoch : Time
        Epoch of the TLE, a single time
    altitude : Quantity
        Distance from the centre of the Earth minus `R_EARTH`, averaged over one
        orbit. Positive.
    ltan : Quantity
        Local mean time of the ascending node, as a time of day, such as 10.5 h
    name : str, optional
        Name of the satellite, kept with the TLE

    Returns
    -------
    tle : Tle
        The element set

    Raises
    ------
    ValueError
        If the altitude is not positive, if no inclination makes the orbit
        sun-synchronous, or if SGP4 rejects the elements. SGP4 treats an orbit of
        225 min or longer as deep space, and this builder rejects it.
    """
    if altitude <= Q_(0, "km"):
        raise ValueError(f"The altitude must be positive, got {altitude}")

    epoch = epoch.utc
    epoch_days = float((epoch.jd1 - _SGP4_EPOCH_ZERO) + epoch.jd2)
    node = _node_right_ascension(epoch, ltan)
    radius = (R_EARTH + altitude).to_value(u.km)

    # Kepler's law for the first guess. SGP4 reads this mean motion as Kozai's.
    mean_motion = float(
        np.sqrt(MU_EARTH / (R_EARTH + altitude) ** 3).to_value("1 / min")
    )
    tolerance = _ALTITUDE_TOLERANCE.to_value(u.km)
    for _ in range(_MAX_ITERATIONS):
        inclination = _sun_synchronous_inclination(epoch_days, mean_motion, node)
        mean_radius = _mean_radius(_satrec(epoch_days, inclination, mean_motion, node))
        if abs(mean_radius - radius) < tolerance:
            break
        mean_motion *= (mean_radius / radius) ** 1.5
    else:
        raise ValueError(
            f"The averaged altitude did not settle within {_MAX_ITERATIONS} rounds"
        )

    return Tle(name, _satrec(epoch_days, inclination, mean_motion, node))


def _satrec(
    epoch_days: float, inclination: float, mean_motion: float, node: float
) -> Satrec:
    """
    An SGP4 object for a circular orbit with no drag, at the ascending node.

    Parameters
    ----------
    epoch_days : float
        Epoch, in days from 1949-12-31 00:00 UTC
    inclination : float
        Inclination [rad]
    mean_motion : float
        Kozai mean motion, as a TLE holds it [rad/min]
    node : float
        Right ascension of the ascending node in TEME [rad]

    Returns
    -------
    satrec : Satrec
        The initialised SGP4 object

    Raises
    ------
    ValueError
        If SGP4 reports an error, or treats the orbit as deep space
    """
    satrec = Satrec()
    satrec.sgp4init(
        WGS72, "i", SATELLITE_NUMBER, epoch_days,
        0.0, 0.0, 0.0,  # B*, and the first and second derivatives of the mean motion
        0.0, 0.0, inclination, 0.0, mean_motion, node,
    )  # fmt: skip
    if satrec.error != 0:
        raise ValueError(
            f"SGP4 rejected the orbit with error code {satrec.error}: "
            f"{SGP4_ERRORS.get(satrec.error, 'unknown error')}"
        )
    if satrec.method == "d":
        raise ValueError(
            "SGP4 treats an orbit of 225 min or longer as deep space. Only near-Earth "
            "sun-synchronous orbits are built."
        )
    return satrec


def _sun_synchronous_inclination(
    epoch_days: float, mean_motion: float, node: float
) -> float:
    """
    The inclination at which SGP4's secular node rate matches the mean sun.

    Parameters
    ----------
    epoch_days : float
        Epoch, in days from 1949-12-31 00:00 UTC
    mean_motion : float
        Kozai mean motion [rad/min]
    node : float
        Right ascension of the ascending node in TEME [rad]

    Returns
    -------
    inclination : float
        The sun-synchronous inclination [rad]

    Raises
    ------
    ValueError
        If even the highest inclination searched turns the node slower than the
        sun. The orbit is then too high to be sun-synchronous.
    """
    target = MEAN_SUN_RATE.to_value("rad / min")
    low, high = _INCLINATION_LOW, _INCLINATION_HIGH
    if _satrec(epoch_days, high, mean_motion, node).nodedot < target:
        raise ValueError(
            "No inclination makes this orbit sun-synchronous. It is too high: its "
            "node turns slower than the sun even close to 180 degrees."
        )
    for _ in range(_BISECTIONS):
        middle = 0.5 * (low + high)
        if _satrec(epoch_days, middle, mean_motion, node).nodedot < target:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def _mean_radius(satrec: Satrec) -> float:
    """
    Distance from the centre of the Earth, averaged over one orbit.

    One orbit here is one nodal period: one turn of the argument of latitude, at
    SGP4's secular rate. SGP4's short-period terms repeat with it, so they average
    out.

    Parameters
    ----------
    satrec : Satrec
        The initialised SGP4 object

    Returns
    -------
    radius : float
        The averaged distance [km]

    Raises
    ------
    ValueError
        If SGP4 fails at any of the points
    """
    period: float = nodal_period(satrec).to(u.min).value
    minutes = np.arange(_SAMPLES_PER_ORBIT) * period / _SAMPLES_PER_ORBIT
    error, position, _ = satrec.sgp4_array(
        np.full(_SAMPLES_PER_ORBIT, satrec.jdsatepoch),
        satrec.jdsatepochF + minutes / 1440,
    )
    if np.any(error):
        raise ValueError("SGP4 failed while averaging the altitude over one orbit")
    return float(np.linalg.norm(position, axis=1).mean())


def _node_right_ascension(epoch: TimeArray, ltan: Quantity) -> float:
    """
    Right ascension in TEME of an ascending node at a local mean time.

    The local mean time at a longitude is UT1 plus the longitude, as a time of
    day. In TEME, a longitude is the right ascension minus the Greenwich mean
    sidereal time of IAU 1982, which is what astropy's TEME frame turns with. So
    the node sits at that sidereal time plus the local mean time minus UT1.

    Parameters
    ----------
    epoch : Time
        The epoch, a single time
    ltan : Quantity
        Local mean time of the ascending node, as a time of day

    Returns
    -------
    node : float
        Right ascension of the ascending node in TEME, from 0 to 2 pi [rad]
    """
    sidereal = epoch.sidereal_time("mean", "greenwich", model="IAU1982")
    ut1_hours = (epoch.ut1.mjd % 1) * 24
    angle = sidereal.to_value(u.rad) + np.radians((ltan.to_value(u.h) - ut1_hours) * 15)
    return float(angle % (2 * np.pi))
