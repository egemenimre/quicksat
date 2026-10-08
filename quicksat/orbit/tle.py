# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
SGP4 element sets, and the states SGP4 computes from them.

An element set is an sgp4 `Satrec` and a name. The `Satrec` holds every element,
so the text it was read from is not kept. A TLE is one way in, and later OMM can
be another: sgp4 reads both into the same `Satrec`. The two TLE lines can always
be written again from the elements, with `Tle.lines`.

A TLE file holds exactly one element set, in two lines or in three with a name
line first. sgp4's fast parser checks very little. It accepts a wrong checksum,
and gives an error code for swapped lines instead of raising. So sgp4's own
checks run first: `verify_checksum`, and its pure-Python parser, which checks the
fixed columns and that both lines name the same satellite.

SGP4 gives positions and velocities in TEME, the true equator and mean equinox
frame of date. astropy's own transform turns them into GCRS, so that they share
a frame with the sun.

"""

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.coordinates import (
    GCRS,
    TEME,
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.time import Time
from astropy.units import Quantity
from sgp4.api import SGP4_ERRORS, WGS72, Satrec
from sgp4.earth_gravity import wgs72
from sgp4.exporter import export_tle
from sgp4.io import twoline2rv, verify_checksum

from quicksat import Q_, u
from quicksat.utils.intervals import TimeArray

MAX_EPOCH_OFFSET = Q_(7, "day")
"""How far a run may start from the TLE epoch before `warn_if_far_from_epoch`
complains. SGP4 loses accuracy away from its epoch."""


@dataclass(frozen=True)
class Tle:
    """
    One element set, ready for SGP4.

    Parameters
    ----------
    name : str or None
        The name of the satellite, if known
    satrec : Satrec
        The initialised sgp4 object, which holds every element
    """

    name: str | None
    satrec: Satrec

    @property
    def epoch(self) -> TimeArray:
        """
        The epoch of the element set.

        Returns
        -------
        epoch : Time
            The epoch, in the UTC time scale
        """
        return Time(
            self.satrec.jdsatepoch, self.satrec.jdsatepochF, format="jd", scale="utc"
        )

    @property
    def nodal_period(self) -> Quantity:
        """
        The time from one ascending node to the next. See `nodal_period`.

        Returns
        -------
        period : Quantity
            The nodal period, in minutes
        """
        return nodal_period(self.satrec)

    @property
    def period(self) -> Quantity:
        """
        One orbit, for a duration in orbits: the nodal period.

        A `Trajectory` has a `period` too, measured from its states. So a run
        reads one orbit the same way from either.

        Returns
        -------
        period : Quantity
            The nodal period, in minutes
        """
        return self.nodal_period

    def states(self, times: TimeArray, with_velocity: bool = True) -> SkyCoord:
        """
        The satellite's state from SGP4, in GCRS. See `tle_states`.

        Parameters
        ----------
        times : Time
            The sample times, as an array
        with_velocity : bool, optional
            Whether the state carries velocities as well as positions. True by
            default.

        Returns
        -------
        state : SkyCoord
            The position, and the velocity if asked for, in GCRS
        """
        return tle_states(self, times, with_velocity)

    @property
    def lines(self) -> tuple[str, str]:
        """
        The two TLE lines, written from the elements by sgp4's exporter.

        TLE text rounds some elements, such as the angles to 0.0001 degrees. The
        element set itself keeps its full precision.

        Returns
        -------
        lines : tuple of str
            Line 1 and line 2
        """
        line1, line2 = export_tle(self.satrec)
        return line1, line2


def nodal_period(satrec: Satrec) -> Quantity:
    """
    The time from one ascending node to the next, at SGP4's secular rates.

    This is one turn of the argument of latitude: the mean anomaly plus the
    argument of perigee. SGP4's short-period terms move each node crossing a
    little, but they average out over an orbit.

    Parameters
    ----------
    satrec : Satrec
        The initialised sgp4 object

    Returns
    -------
    period : Quantity
        The nodal period, in minutes
    """
    return Q_(2 * np.pi / (satrec.mdot + satrec.argpdot), "min")


def read_tle_file(path: str | Path) -> Tle:
    """
    Read a file holding exactly one TLE.

    The file has two lines, or three with a name line first. Blank lines are
    ignored. sgp4 checks both checksums, the fixed columns, and that both lines
    name the same satellite. SGP4 must then initialise without an error.

    Parameters
    ----------
    path : str | Path
        Filepath of the TLE file

    Returns
    -------
    tle : Tle
        The checked element set

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the file does not hold exactly one valid TLE, or if SGP4 reports an
        error when it initialises from it
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")

    lines = [line.rstrip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) == 2:
        name, (line1, line2) = None, lines
    elif len(lines) == 3:
        if lines[0].startswith("1 ") and lines[1].startswith("2 "):
            raise ValueError(
                f"{path}: the name line must come first, before the two TLE lines"
            )
        name, line1, line2 = lines[0].strip(), lines[1], lines[2]
    else:
        raise ValueError(
            f"{path}: a TLE file holds exactly one TLE, in two lines or in three "
            f"with a name line first. Found {len(lines)} non-blank lines."
        )

    try:
        verify_checksum(line1, line2)
        # sgp4's pure-Python parser checks the columns, which its fast one does not
        twoline2rv(line1, line2, wgs72)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error

    satrec = Satrec.twoline2rv(line1, line2, WGS72)
    if satrec.error != 0:
        raise ValueError(
            f"{path}: SGP4 rejected the TLE with error code {satrec.error}: "
            f"{SGP4_ERRORS.get(satrec.error, 'unknown error')}"
        )
    return Tle(name, satrec)


def warn_if_far_from_epoch(tle: Tle, time: TimeArray) -> None:
    """
    Warn if a time is more than 7 days from the epoch of the TLE.

    SGP4 loses accuracy away from the epoch of its element set. A run that starts
    a week or more from it should not be trusted.

    Parameters
    ----------
    tle : Tle
        The element set
    time : Time
        The time to compare against the epoch, normally the start of the run
    """
    offset = float(abs((time - tle.epoch).to_value(u.day)))
    if offset > MAX_EPOCH_OFFSET.to(u.day).value:
        warnings.warn(
            f"The run starts {offset:.1f} days from the TLE epoch "
            f"({tle.epoch.utc.isot} UTC). SGP4 loses accuracy away from its epoch, "
            f"so use a TLE within {MAX_EPOCH_OFFSET.to(u.day).value:.0f} days of "
            "the start.",
            stacklevel=2,
        )


def tle_states(tle: Tle, times: TimeArray, with_velocity: bool = True) -> SkyCoord:
    """
    The satellite's state from SGP4, in GCRS.

    The whole `Time` array goes through SGP4 in one call, with sgp4's
    `sgp4_array`, and through the frame transform in one call. There is no loop
    over the samples. SGP4 takes UTC, so the times may be in any time scale.

    astropy transforms velocities about five times slower than positions. So a
    caller that needs positions only, such as the eclipse search, leaves them out.

    Parameters
    ----------
    tle : Tle
        The element set
    times : Time
        The sample times, as an array
    with_velocity : bool, optional
        Whether the state carries velocities as well as positions. True by
        default.

    Returns
    -------
    state : SkyCoord
        The position of the satellite relative to the centre of the Earth, and its
        velocity if asked for, in GCRS. Its `obstime` is `times`.

    Raises
    ------
    ValueError
        If SGP4 returns an error code for any of the times
    """
    utc = times.utc
    error, position, velocity = tle.satrec.sgp4_array(
        np.atleast_1d(utc.jd1), np.atleast_1d(utc.jd2)
    )
    if np.any(error):
        codes = sorted({int(code) for code in np.atleast_1d(error) if code})
        reasons = "; ".join(f"{code}: {SGP4_ERRORS[code]}" for code in codes)
        raise ValueError(f"SGP4 failed for some of the times. Error codes: {reasons}")

    data = CartesianRepresentation(Q_(np.atleast_2d(position).T, "km"))
    if with_velocity:
        data = data.with_differentials(
            CartesianDifferential(Q_(np.atleast_2d(velocity).T, "km/s"))
        )
    return SkyCoord(TEME(data, obstime=times).transform_to(GCRS(obstime=times)))
