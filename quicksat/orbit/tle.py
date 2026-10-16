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

A TLE file holds one element set or several, each in two lines or in three with
a name line first, as CelesTrak and Space-Track give a group of satellites.
`read_tle_file` takes one: the file's only one, or the satellite asked for, by
its name or its catalogue number.

sgp4's fast parser checks very little. It accepts a wrong checksum, and gives an
error code for swapped lines instead of raising. So sgp4's own checks run first:
`verify_checksum`, and its pure-Python parser, which checks the fixed columns and
that both lines name the same satellite.

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
"""How far either end of a run may be from the epoch of an element set before
`warn_if_far_from_epoch` complains. SGP4 loses accuracy away from its epoch."""


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


def _name(line: str) -> str:
    """
    A TLE's name line, without the padding, and without the `0 ` that
    Space-Track's three-line form puts in front.

    Parameters
    ----------
    line : str
        The name line

    Returns
    -------
    name : str
        The satellite's name
    """
    name = line.strip()
    return name[2:].strip() if name.startswith("0 ") else name


def _element_set(name: str | None, line1: str, line2: str, where: str) -> Tle:
    """
    One TLE, checked by sgp4, and initialised.

    Parameters
    ----------
    name : str or None
        The name line's satellite, if there is a name line
    line1, line2 : str
        The two TLE lines
    where : str
        The file and the line, for the messages

    Returns
    -------
    tle : Tle
        The checked element set

    Raises
    ------
    ValueError
        If sgp4 finds a wrong checksum or a wrong column, or SGP4 reports an
        error when it initialises
    """
    try:
        verify_checksum(line1, line2)
        # sgp4's pure-Python parser checks the columns, which its fast one does not
        twoline2rv(line1, line2, wgs72)
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from error

    satrec = Satrec.twoline2rv(line1, line2, WGS72)
    if satrec.error != 0:
        raise ValueError(
            f"{where}: SGP4 rejected the TLE with error code {satrec.error}: "
            f"{SGP4_ERRORS.get(satrec.error, 'unknown error')}"
        )
    return Tle(name, satrec)


def read_tle_sets(path: str | Path) -> list[Tle]:
    """
    Read every TLE in a file.

    Each TLE has two lines, or three with a name line first, as CelesTrak and
    Space-Track give a group of satellites. Blank lines are ignored. sgp4 checks
    both checksums, the fixed columns, and that both lines name the same
    satellite. SGP4 must then initialise without an error.

    Parameters
    ----------
    path : str | Path
        Filepath of the TLE file

    Returns
    -------
    tles : list of Tle
        The checked element sets, in the file's order

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the file holds no TLE, a line belongs to no TLE, or a TLE is not
        valid
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")

    lines = [
        (number, line.rstrip())
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if line.strip()
    ]
    if not lines:
        raise ValueError(f"{path}: the file holds no TLE")

    def is_pair(index: int) -> bool:
        return (
            index + 1 < len(lines)
            and lines[index][1].startswith("1 ")
            and lines[index + 1][1].startswith("2 ")
        )

    tles, index = [], 0
    while index < len(lines):
        number, line = lines[index]
        if is_pair(index):
            where = f"{path}, line {number}"
            tles.append(_element_set(None, line, lines[index + 1][1], where))
            index += 2
        elif is_pair(index + 1):
            where = f"{path}, line {lines[index + 1][0]}"
            line1, line2 = lines[index + 1][1], lines[index + 2][1]
            tles.append(_element_set(_name(line), line1, line2, where))
            index += 3
        else:
            raise ValueError(
                f"{path}, line {number}: '{line.strip()}' is not part of a TLE. A TLE "
                "is two lines, which start with 1 and 2. A name line must come "
                "first, if there is one."
            )
    return tles


_LISTED = 10
"""Most element sets that a message lists by name."""


def _label(tle: Tle) -> str:
    """An element set's name and catalogue number, for the messages."""
    number = tle.satrec.satnum
    return f"{tle.name} ({number})" if tle.name else f"catalogue number {number}"


def _is_satellite(tle: Tle, satellite: str | int) -> bool:
    """
    Whether an element set is the satellite asked for: by its catalogue number,
    or by its name, whatever the case and the spaces.
    """
    wanted = " ".join(str(satellite).split()).casefold()
    if wanted.isdigit() and int(wanted) == tle.satrec.satnum:
        return True
    return tle.name is not None and " ".join(tle.name.split()).casefold() == wanted


def pick_element_set(
    element_sets: list[Tle], satellite: str | int | None, path: str | Path
) -> Tle:
    """
    One of a file's element sets: the only one, or the satellite asked for.

    Parameters
    ----------
    element_sets : list of Tle
        The file's element sets
    satellite : str or int or None
        The satellite's name, or its catalogue number. None takes the file's
        only element set.
    path : str | Path
        The file, for the messages

    Returns
    -------
    tle : Tle
        The element set

    Raises
    ------
    ValueError
        If no satellite is asked for and the file holds several element sets, if
        none is the satellite asked for, or if several are
    """
    labels = [_label(tle) for tle in element_sets[:_LISTED]]
    if len(element_sets) > _LISTED:
        labels.append(f"and {len(element_sets) - _LISTED} more")
    listed = ", ".join(labels)
    if satellite is None:
        if len(element_sets) == 1:
            return element_sets[0]
        raise ValueError(
            f"{path} holds {len(element_sets)} element sets, so it is not clear "
            f"which one to take: {listed}"
        )
    found = [tle for tle in element_sets if _is_satellite(tle, satellite)]
    if not found:
        raise ValueError(
            f"{path} holds no element set named or numbered '{satellite}'. It "
            f"holds: {listed}"
        )
    if len(found) > 1:
        epochs = ", ".join(f"{tle.epoch.utc.isot} UTC" for tle in found)
        raise ValueError(
            f"{path} holds {len(found)} element sets for '{satellite}', with the "
            f"epochs {epochs}. Keep one of them in the file."
        )
    return found[0]


def read_tle_file(path: str | Path, satellite: str | int | None = None) -> Tle:
    """
    Read one TLE from a file: its only one, or the satellite asked for.

    See `read_tle_sets` for the file, and `pick_element_set` for the choice.

    Parameters
    ----------
    path : str | Path
        Filepath of the TLE file
    satellite : str or int, optional
        The satellite's name, or its catalogue number, for a file that holds
        several. Without it, the file must hold one TLE.

    Returns
    -------
    tle : Tle
        The checked element set

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If a TLE in the file is not valid, or the file does not hold the one TLE
        asked for
    """
    return pick_element_set(read_tle_sets(path), satellite, path)


def warn_if_far_from_epoch(
    tle: Tle,
    start: TimeArray,
    end: TimeArray | None = None,
    label: str = "the TLE",
) -> str | None:
    """
    Warn if either end of a run is more than 7 days from the epoch of an element
    set.

    SGP4 loses accuracy away from the epoch of its element set. A run that starts
    or ends a week or more from it should not be trusted.

    Parameters
    ----------
    tle : Tle
        The element set
    start : Time
        The start of the run
    end : Time, optional
        The end of the run. Without it, the start alone is checked.
    label : str, optional
        What the element set is, for the message, such as `the TLE`

    Returns
    -------
    text : str or None
        The warning's text, so that a run can show it too, or None if both ends
        are close enough
    """
    ends = {"starts": start} if end is None else {"starts": start, "ends": end}
    offsets = {
        word: float(abs((time - tle.epoch).to_value(u.day)))
        for word, time in ends.items()
    }
    word = max(offsets, key=lambda key: offsets[key])
    limit = MAX_EPOCH_OFFSET.to(u.day).value
    if offsets[word] <= limit:
        return None
    text = (
        f"The run {word} {offsets[word]:.1f} days from the epoch of {label} "
        f"({tle.epoch.utc.isot} UTC). SGP4 loses accuracy away from its epoch, so "
        f"use an element set within {limit:.0f} days of the whole run."
    )
    warnings.warn(text, stacklevel=2)
    return text


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
