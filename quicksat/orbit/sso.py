# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Sun-synchronous orbits, built as a TLE that SGP4 reads as asked.

Each element is set against SGP4 itself: the inclination makes its node rate match the
mean sun, the mean motion makes its altitude, averaged over an orbit, the one asked for,
and the node sits at the asked local time. `docs/scenario/scenario_ref.ipynb`, under "A
sun-synchronous orbit", explains why.

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
"""The lower end of the search for the inclination, 90 degrees, in rad."""

_INCLINATION_HIGH = float(np.radians(179.9))
"""The upper end of the search, 179.9 degrees, in rad, short of SGP4's division at 180."""

_BISECTIONS = 60
"""Halvings of the inclination range, well past the precision of a float."""


def sso_tle(
    epoch: TimeArray, altitude: Quantity, ltan: Quantity, name: str | None = None
) -> Tle:
    """
    A TLE for a circular sun-synchronous orbit, with the satellite at the ascending node
    at the epoch.

    Parameters
    ----------
    epoch : Time
        The TLE's epoch, a single time
    altitude : Quantity
        The distance from the Earth's centre less `R_EARTH`, averaged over one orbit,
        positive
    ltan : Quantity
        The local mean time of the ascending node, such as 10.5 h
    name : str, optional
        The satellite's name

    Returns
    -------
    tle : Tle
        The element set, at full precision

    Raises
    ------
    ValueError
        If the altitude is not positive, no inclination is sun-synchronous, or SGP4
        refuses the elements, such as a deep-space orbit of 225 min or more
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
    An SGP4 object for a circular orbit with no drag, at the ascending node, from the
    epoch in days since 1949-12-31, the inclination and the node in rad, and the mean
    motion in rad/min.
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
    The inclination, in rad, at which SGP4's node rate matches the mean sun, or an error
    for an orbit too high.
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
    """The distance from the Earth's centre, in km, averaged over one nodal period."""
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
    The right ascension in TEME of an ascending node at a local mean time, from 0 to 2
    pi, in rad.
    """
    sidereal = epoch.sidereal_time("mean", "greenwich", model="IAU1982")
    ut1_hours = (epoch.ut1.mjd % 1) * 24
    angle = sidereal.to_value(u.rad) + np.radians((ltan.to_value(u.h) - ut1_hours) * 15)
    return float(angle % (2 * np.pi))
