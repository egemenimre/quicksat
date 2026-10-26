# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Trajectory files in CCSDS OEM, the Orbit Ephemeris Message, in its KVN form.

An OEM holds a header, then segments of metadata, data lines and an optional covariance.
The data lines give an epoch, the position in km and the velocity in km/s. The centre
must be the Earth, and quicksat's own splines replace the file's interpolation. Each
segment becomes a segment of the `Trajectory`, so a manoeuvre between two is kept.
`docs/scenario/scenario_ref.ipynb`, under "A CCSDS OEM", explains what is read.

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
"""OEM frames, each with the name in `quicksat.orbit.trajectory.FRAMES` it is read as.
Every ITRF realisation is read as ITRS."""

WITHOUT_POLAR_MOTION = ("GRC", "TDR")
"""OEM frames that turn with the Earth without polar motion, which astropy lacks, so
they are refused."""

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
"""OEM time systems, each with the astropy scale it is read in. GPS is read as TAI less
`GPS_BEHIND_TAI`."""

GPS_BEHIND_TAI = Q_(19, "s")
"""GPS time runs this far behind TAI."""


@dataclass
class _OemSegment:
    """
    One segment as the parser found it: the line of its `META_START`, its metadata with
    their lines, and its data lines' epochs, lines and values.
    """

    line: int
    meta: dict[str, tuple[str, int]] = field(default_factory=dict)
    epochs: list[str] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    values: list[list[float]] = field(default_factory=list)


def _data_line(line: str, number: int, path: Path, segment: _OemSegment) -> None:
    """
    Adds a data line to its segment, refusing one without an epoch and 6 or 9 numbers.
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
    Reads an OEM line by line, checking the layout only, with one method for each place
    in the file.

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
            The line, stripped
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
            The segments, in the file's order

        Raises
        ------
        ValueError
            If the file ends inside a block, or a segment has no data
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
    The header and the segments of an OEM, with an error naming the line where the
    layout breaks.
    """
    parser = _Parser(path)
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("COMMENT"):
            parser.feed(line, number)
    return parser.finish()


def _epochs(texts: list[str], lines: list[int], system: str, path: Path) -> TimeArray:
    """
    OEM epochs as times in the segment's time system, with an error naming the line of
    one that is not a time.
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
    The name in `quicksat.orbit.trajectory.FRAMES` that an OEM frame is read as, or an
    error, with a way out for GRC and TDR.
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
    """Checks a segment's metadata, and gives its time system."""
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
    A segment's states, in its frame, and the useable span it serves, or None where it
    gives none.
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
    Read a CCSDS OEM in KVN.

    Parameters
    ----------
    path : str or Path
        The OEM file

    Returns
    -------
    trajectory : Trajectory
        The trajectory, in GCRS, with a segment for each of the OEM's

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the layout breaks or a value is not read, naming the line, or the segments
        overlap
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
    Write states to an OEM in KVN, version 2.0, as one segment in UTC, to the
    microsecond and the millimetre.

    Parameters
    ----------
    path : str or Path
        The file to write
    state : SkyCoord
        Positions with velocities, with their times
    frame : str, optional
        One of `OEM_FRAMES`, or an ITRF realisation, by default EME2000
    name, object_id : str, optional
        The `OBJECT_NAME` and `OBJECT_ID`, by default `UNKNOWN`
    creation_date : Time, optional
        The `CREATION_DATE`, by default now

    Returns
    -------
    path : Path
        The file written
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
