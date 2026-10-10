# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Trajectory files in CCSDS OEM, the Orbit Ephemeris Message, in its KVN form.

An OEM is plain text: a header, then one or more segments. Each segment is a
block of metadata between `META_START` and `META_STOP`, its data lines, and an
optional covariance block:

    CCSDS_OEM_VERS = 2.0
    CREATION_DATE = 2026-10-01T00:00:00
    ORIGINATOR = SOMEONE

    META_START
    OBJECT_NAME = MY SATELLITE
    OBJECT_ID = 2026-001A
    CENTER_NAME = EARTH
    REF_FRAME = EME2000
    TIME_SYSTEM = UTC
    START_TIME = 2026-10-01T00:00:00.000
    STOP_TIME = 2026-10-02T00:00:00.000
    META_STOP
    2026-10-01T00:00:00.000 -5288.590862 1338.957773 -4213.430985 ...

Each data line holds an epoch, the position in km and the velocity in km/s.
Three accelerations may follow, and are not read. Covariance blocks and comments
are skipped. Versions 1.0, 2.0 and 3.0 share this layout. An epoch is a date,
`2026-10-01T00:00:00`, or a day of the year, `2026-274T00:00:00`.

The centre must be the Earth. OEM names the axes apart from the origin, so ICRF
centred on the Earth is GCRS. The frames read are in `OEM_FRAMES`, with every
ITRF realisation read as ITRS, and the time systems in `TIME_SYSTEMS`. The
interpolation the file suggests is not followed: quicksat uses its own splines,
as for ECSV.

Each segment becomes a segment of the `Trajectory`, so that a manoeuvre between
two segments is not smoothed over. A segment serves its useable span where it
gives one, and all its data otherwise.

"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import numpy as np
from astropy.coordinates import (
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.time import Time

from quicksat import Q_, u
from quicksat.orbit.ccsds import key_value, normalised_epoch
from quicksat.orbit.trajectory import Trajectory, frame_of
from quicksat.utils.intervals import TimeArray

VERSIONS = ("1.0", "2.0", "3.0")
"""The OEM versions read. They share the layout this reader uses."""

OEM_FRAMES = {
    "EME2000": "EME2000",
    "GCRF": "GCRS",
    "ICRF": "GCRS",
    "TEME": "TEME",
    "TOD": "TETE",
    "CIRF": "CIRS",
}
"""OEM frames, each with the name in `quicksat.orbit.trajectory.FRAMES` that it
is read as. Every ITRF realisation, such as `ITRF2000` or `ITRF-97`, is read as
ITRS."""

WITHOUT_POLAR_MOTION = ("GRC", "TDR")
"""OEM frames that turn with the Earth but leave out polar motion. astropy has
no such frame, so they are refused."""

TIME_SYSTEMS = {
    "UTC": "utc",
    "TAI": "tai",
    "TT": "tt",
    "TDB": "tdb",
    "TCB": "tcb",
    "TCG": "tcg",
    "UT1": "ut1",
    "GPS": "tai",
}
"""OEM time systems, each with the astropy scale it is read in. GPS time is read
as TAI, less `GPS_BEHIND_TAI`."""

GPS_BEHIND_TAI = Q_(19, "s")
"""GPS time runs this far behind TAI."""


@dataclass
class _OemSegment:
    """
    One segment as the parser found it, before any of it is understood.

    Parameters
    ----------
    line : int
        The line of its `META_START`
    meta : dict
        Each metadata key, with its value and its line
    epochs : list of str
        The epoch of each data line, as written
    lines : list of int
        The line of each data line
    values : list of list of float
        The position and the velocity on each data line
    """

    line: int
    meta: dict[str, tuple[str, int]] = field(default_factory=dict)
    epochs: list[str] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    values: list[list[float]] = field(default_factory=list)


def _data_line(line: str, number: int, path: Path, segment: _OemSegment) -> None:
    """
    Add a data line to its segment.

    Parameters
    ----------
    line : str
        The line, without the spaces at its ends
    number : int
        Its line number
    path : Path
        The file, for the messages
    segment : _OemSegment
        The segment the line belongs to

    Raises
    ------
    ValueError
        If the line does not hold an epoch and 6 numbers, or 9 with the
        accelerations
    """
    tokens = line.split()
    if len(tokens) not in (7, 10):
        raise ValueError(
            f"{path}, line {number}: a data line holds an epoch and 6 numbers, or 9 "
            f"with the accelerations. This one holds {len(tokens) - 1}."
        )
    try:
        values = [float(token) for token in tokens[1:7]]
    except ValueError as error:
        raise ValueError(f"{path}, line {number}: {error}") from error
    segment.epochs.append(tokens[0])
    segment.lines.append(number)
    segment.values.append(values)


class _Parser:
    """
    Reads an OEM line by line, and keeps track of where it is.

    It is in one of six places: before the version, in the header, in a
    segment's metadata, data or covariance, or after the covariance. Each has a
    method that takes the next line. The parser checks the layout only. What
    the values mean is checked later, segment by segment.

    Parameters
    ----------
    path : Path
        The file, for the messages
    """

    def __init__(self, path: Path):
        self.path = path
        self.header: dict[str, tuple[str, int]] = {}
        self.segments: list[_OemSegment] = []
        self.place = "start"
        self._handlers = {
            "start": self._in_start,
            "header": self._in_header,
            "meta": self._in_meta,
            "data": self._in_data,
            "covariance": self._in_covariance,
            "after": self._in_after,
        }

    def _error(self, number: int, message: str) -> ValueError:
        """An error that names the file and the line."""
        return ValueError(f"{self.path}, line {number}: {message}")

    def feed(self, line: str, number: int) -> None:
        """
        Take the next line that is neither blank nor a comment.

        Parameters
        ----------
        line : str
            The line, without the spaces at its ends
        number : int
            Its line number

        Raises
        ------
        ValueError
            If the line does not belong where the parser is
        """
        if line == "META_START" and self.place not in ("start", "meta", "covariance"):
            self.segments.append(_OemSegment(number))
            self.place = "meta"
            return
        self._handlers[self.place](line, number)

    def _in_start(self, line: str, number: int) -> None:
        """The version, which comes first."""
        if not line.startswith("CCSDS_OEM_VERS"):
            raise self._error(number, "an OEM starts with CCSDS_OEM_VERS")
        key, value = key_value(line, number, self.path)
        if value not in VERSIONS:
            raise self._error(
                number,
                f"OEM version {value} is not read. It must be one of: "
                f"{', '.join(VERSIONS)}",
            )
        self.header[key], self.place = (value, number), "header"

    def _in_header(self, line: str, number: int) -> None:
        """A key of the header."""
        key, value = key_value(line, number, self.path)
        self.header[key] = (value, number)

    def _in_meta(self, line: str, number: int) -> None:
        """A key of the metadata, or its end."""
        if line == "META_STOP":
            self.place = "data"
        elif "=" not in line and line[:1].isdigit():
            raise self._error(
                number, "a data line inside the metadata. Is META_STOP missing?"
            )
        else:
            key, value = key_value(line, number, self.path)
            self.segments[-1].meta[key] = (value, number)

    def _in_data(self, line: str, number: int) -> None:
        """A data line, or the start of the covariance."""
        if line == "COVARIANCE_START":
            self.place = "covariance"
        else:
            _data_line(line, number, self.path, self.segments[-1])

    def _in_covariance(self, line: str, number: int) -> None:
        """A line of the covariance, which is skipped, or its end."""
        if line == "COVARIANCE_STOP":
            self.place = "after"

    def _in_after(self, line: str, number: int) -> None:
        """Anything but a new segment, after the covariance."""
        raise self._error(
            number,
            "a data line after the covariance. A segment's data comes before its "
            "covariance.",
        )

    def finish(self) -> tuple[dict[str, tuple[str, int]], list[_OemSegment]]:
        """
        The header and the segments, once every line is in.

        Returns
        -------
        header : dict
            Each header key, with its value and its line
        segments : list of _OemSegment
            The segments, in the order of the file

        Raises
        ------
        ValueError
            If the file ends inside a block, or has a segment with no data
        """
        ends = {"start": "CCSDS_OEM_VERS", "meta": "META_STOP"}
        if self.place in ("start", "meta", "covariance"):
            missing = ends.get(self.place, "COVARIANCE_STOP")
            raise ValueError(f"{self.path}: the file ends with no {missing}")
        if not self.segments:
            raise ValueError(f"{self.path}: the file has no segments")
        for segment in self.segments:
            if not segment.epochs:
                raise self._error(segment.line, "the segment has no data lines")
        return self.header, self.segments


def _parse(
    text: str, path: Path
) -> tuple[dict[str, tuple[str, int]], list[_OemSegment]]:
    """
    The header and the segments of an OEM, read line by line. See `_Parser`.

    Parameters
    ----------
    text : str
        The file's text
    path : Path
        The file, for the messages

    Returns
    -------
    header : dict
        Each header key, with its value and its line
    segments : list of _OemSegment
        The segments, in the order of the file

    Raises
    ------
    ValueError
        If the layout is broken, naming the line
    """
    parser = _Parser(path)
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("COMMENT"):
            parser.feed(line, number)
    return parser.finish()


def _epochs(texts: list[str], lines: list[int], system: str, path: Path) -> TimeArray:
    """
    OEM epochs as times, in the segment's time system.

    Parameters
    ----------
    texts : list of str
        The epochs as written
    lines : list of int
        The line of each, for the message
    system : str
        The time system, one of `TIME_SYSTEMS`
    path : Path
        The file, for the message

    Returns
    -------
    times : Time
        The epochs, as an array

    Raises
    ------
    ValueError
        If an epoch is not a time, naming its line
    """
    scale = TIME_SYSTEMS[system]
    try:
        times = Time([normalised_epoch(text) for text in texts], scale=scale)
    except ValueError:
        for text, line in zip(texts, lines, strict=True):
            try:
                Time(normalised_epoch(text), scale=scale)
            except ValueError as error:
                raise ValueError(
                    f"{path}, line {line}: '{text}' is not an epoch"
                ) from error
        raise ValueError(
            f"{path}: the epochs mix a date with a day of the year"
        ) from None
    if system == "GPS":
        times = times + GPS_BEHIND_TAI
    return times


def _frame(name: str, line: int, path: Path) -> str:
    """
    The name in `quicksat.orbit.trajectory.FRAMES` that an OEM frame is read as.

    Parameters
    ----------
    name : str
        The OEM's `REF_FRAME`
    line : int
        Its line, for the message
    path : Path
        The file, for the message

    Returns
    -------
    frame : str

    Raises
    ------
    ValueError
        If the frame is not read, with a way out for GRC and TDR
    """
    key = name.strip().upper()
    if key in OEM_FRAMES:
        return OEM_FRAMES[key]
    if key.startswith("ITRF"):
        return "ITRS"
    if key in WITHOUT_POLAR_MOTION:
        raise ValueError(
            f"{path}, line {line}: REF_FRAME = {name} turns with the Earth but leaves "
            "out polar motion, and astropy has no such frame. If an error of about "
            "10 m will do, change REF_FRAME to ITRF in the file by hand, and "
            "quicksat reads it as ITRS."
        )
    raise ValueError(
        f"{path}, line {line}: REF_FRAME = {name} is not read. It must be one of: "
        f"{', '.join(OEM_FRAMES)}, or an ITRF realisation such as ITRF2000"
    )


def _check_metadata(segment: _OemSegment, path: Path) -> str:
    """
    Check what a segment's metadata says, and give its time system.

    Parameters
    ----------
    segment : _OemSegment
        The segment
    path : Path
        The file, for the messages

    Returns
    -------
    system : str
        The time system, one of `TIME_SYSTEMS`

    Raises
    ------
    ValueError
        If a key is missing, the centre is not the Earth, the frame has a
        `REF_FRAME_EPOCH`, or the time system is not read
    """
    meta = segment.meta
    needed = ("CENTER_NAME", "REF_FRAME", "TIME_SYSTEM", "START_TIME", "STOP_TIME")
    missing = [key for key in needed if key not in meta]
    if missing:
        raise ValueError(
            f"{path}, line {segment.line}: the metadata has no {', '.join(missing)}"
        )
    centre, line = meta["CENTER_NAME"]
    if centre.strip().upper() != "EARTH":
        raise ValueError(
            f"{path}, line {line}: CENTER_NAME = {centre}. quicksat reads orbits "
            "around the Earth only."
        )
    if "REF_FRAME_EPOCH" in meta:
        raise ValueError(
            f"{path}, line {meta['REF_FRAME_EPOCH'][1]}: REF_FRAME_EPOCH is not "
            "read. quicksat takes the frame as of each epoch."
        )
    system, line = meta["TIME_SYSTEM"]
    system = system.strip().upper()
    if system not in TIME_SYSTEMS:
        raise ValueError(
            f"{path}, line {line}: TIME_SYSTEM = {system} is not read. It must be "
            f"one of: {', '.join(TIME_SYSTEMS)}"
        )
    return system


def _segment_states(
    segment: _OemSegment, path: Path
) -> tuple[SkyCoord, tuple[TimeArray, TimeArray] | None]:
    """
    A segment's states, and the span it serves.

    Parameters
    ----------
    segment : _OemSegment
        The segment, as parsed
    path : Path
        The file, for the messages

    Returns
    -------
    state : SkyCoord
        The positions and velocities, in the segment's frame
    span : tuple of Time, or None
        The useable start and stop, where the segment gives either. A missing
        one is taken from the data. None where the segment gives neither.

    Raises
    ------
    ValueError
        If the metadata is not read, the epochs do not rise, or an epoch or the
        useable span lies outside the segment's start and stop, naming the line
    """
    system = _check_metadata(segment, path)
    meta = segment.meta

    def epoch_of(key: str) -> TimeArray:
        value, line = meta[key]
        return _epochs([value], [line], system, path)[0]

    times = _epochs(segment.epochs, segment.lines, system, path)
    seconds = (times - times[0]).to_value(u.s)
    falling = np.flatnonzero(np.diff(seconds) <= 0)
    if len(falling):
        raise ValueError(
            f"{path}, line {segment.lines[falling[0] + 1]}: the epochs must rise, "
            "with no repeats"
        )
    start, stop = epoch_of("START_TIME"), epoch_of("STOP_TIME")
    tolerance = Q_(1, "us")
    outside = np.flatnonzero((times < start - tolerance) | (times > stop + tolerance))
    if len(outside):
        raise ValueError(
            f"{path}, line {segment.lines[outside[0]]}: the epoch lies outside "
            "START_TIME and STOP_TIME"
        )

    span = None
    if "USEABLE_START_TIME" in meta or "USEABLE_STOP_TIME" in meta:
        first = (
            epoch_of("USEABLE_START_TIME") if "USEABLE_START_TIME" in meta else times[0]
        )
        last = (
            epoch_of("USEABLE_STOP_TIME") if "USEABLE_STOP_TIME" in meta else times[-1]
        )
        if first < times[0] - tolerance or last > times[-1] + tolerance:
            raise ValueError(
                f"{path}, line {segment.line}: the useable span reaches past the "
                "segment's data lines"
            )
        span = (first, last)

    frame_class, attributes = frame_of(_frame(*meta["REF_FRAME"], path))
    values = np.array(segment.values)
    data = CartesianRepresentation(
        Q_(values[:, :3].T, "km"),
        differentials=CartesianDifferential(Q_(values[:, 3:].T, "km/s")),
    )
    return SkyCoord(frame_class(data, obstime=times, **attributes)), span


def read_oem_trajectory(path: str | Path) -> Trajectory:
    """
    Read a CCSDS OEM in KVN. See the module notes for what is read.

    Parameters
    ----------
    path : str | Path
        Filepath of the OEM

    Returns
    -------
    trajectory : Trajectory
        The trajectory, in GCRS, with a segment for each of the OEM's

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the layout is broken or a value is not read, naming the line, or if
        the segments overlap
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")
    header, segments = _parse(path.read_text(), path)
    states, spans = zip(
        *(_segment_states(segment, path) for segment in segments), strict=True
    )
    # the frames as the file names them, once each
    frames = list(dict.fromkeys(s.meta["REF_FRAME"][0].strip() for s in segments))
    name = segments[0].meta.get("OBJECT_NAME", (None, 0))[0]
    try:
        trajectory = Trajectory.from_segments(
            list(states), list(spans), name=name, frame=", ".join(frames)
        )
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    trajectory.file = path.name
    trajectory.format = "OEM"
    trajectory.originator = header.get("ORIGINATOR", (None, 0))[0]
    return trajectory


def write_oem_trajectory(  # noqa: V103
    path: str | Path,
    state: SkyCoord,
    frame: str = "EME2000",
    name: str | None = None,
    object_id: str | None = None,
    creation_date: TimeArray | None = None,
) -> Path:
    """
    Write states to an OEM in KVN, version 2.0, as one segment in UTC.

    Parameters
    ----------
    path : str | Path
        The file to write
    state : SkyCoord
        Positions with velocities, with an `obstime` for each, such as from
        `tle_states`
    frame : str, optional
        The OEM frame to write the states in: one of `OEM_FRAMES`, or an ITRF
        realisation. EME2000 by default.
    name, object_id : str, optional
        The `OBJECT_NAME` and `OBJECT_ID`, `UNKNOWN` by default
    creation_date : Time, optional
        The `CREATION_DATE`, now by default. Give one for a file that must not
        change from one run to the next.

    Returns
    -------
    path : Path
        The file written. It keeps a microsecond, a millimetre and a micrometre
        a second.
    """
    path = Path(path)
    frame_class, attributes = frame_of(_frame(frame, 0, path))
    times: TimeArray = state.obstime
    cartesian = state.transform_to(frame_class(obstime=times, **attributes)).cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    velocity = cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    # the epochs to the microsecond, as text
    stamps: list[str] = cast(np.ndarray, Time(times.utc, precision=6).isot).tolist()
    created = Time.now() if creation_date is None else creation_date
    lines = [
        "CCSDS_OEM_VERS = 2.0",
        f"CREATION_DATE = {Time(created.utc, precision=0).isot}",
        "ORIGINATOR = quicksat",
        "",
        "META_START",
        f"OBJECT_NAME = {name or 'UNKNOWN'}",
        f"OBJECT_ID = {object_id or 'UNKNOWN'}",
        "CENTER_NAME = EARTH",
        f"REF_FRAME = {frame.strip().upper()}",
        "TIME_SYSTEM = UTC",
        f"START_TIME = {stamps[0]}",
        f"STOP_TIME = {stamps[-1]}",
        "META_STOP",
        "",
    ]
    positions = cartesian.xyz.to_value(u.km).T
    velocities = velocity.d_xyz.to_value(u.km / u.s).T
    for stamp, (x, y, z), (vx, vy, vz) in zip(
        stamps, positions, velocities, strict=True
    ):
        lines.append(f"{stamp} {x:.6f} {y:.6f} {z:.6f} {vx:.9f} {vy:.9f} {vz:.9f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path
