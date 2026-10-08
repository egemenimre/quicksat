# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Trajectory files in ECSV, astropy's CSV with a YAML header.

The header gives each column's unit, and the metadata says what the numbers
mean:

    # %ECSV 1.0
    # ---
    # datatype:
    # - {name: time, unit: s, datatype: float64}
    # - {name: x, unit: km, datatype: float64}
    # ... y and z, then vx, vy and vz in km / s
    # meta:
    #   epoch: 2026-10-01T00:00:00.000
    #   time_scale: utc
    #   frame: ITRS
    #   object_name: My satellite
    time x y z vx vy vz
    0.0 ...

`time` is the time since `epoch`. `epoch`, `time_scale` and `frame` are required,
and `object_name` is optional. Any unit of time, length and speed will do. The
frame is one of `quicksat.orbit.trajectory.FRAMES`.

"""

from pathlib import Path

import numpy as np
from astropy.coordinates import (
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.table import Column, QTable, Table
from astropy.time import TIME_SCALES, Time
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.trajectory import Trajectory, frame_of
from quicksat.utils.intervals import TimeArray

COLUMNS = {
    "time": u.s,
    "x": u.km,
    "y": u.km,
    "z": u.km,
    "vx": u.km / u.s,
    "vy": u.km / u.s,
    "vz": u.km / u.s,
}
"""The columns of a trajectory file, and the unit each is read in."""

WRITTEN_DECIMALS = {
    "time": 6,
    "x": 6,
    "y": 6,
    "z": 6,
    "vx": 9,
    "vy": 9,
    "vz": 9,
}
"""Decimals that `write_ecsv_trajectory` keeps, in the units of `COLUMNS`: a
microsecond, a millimetre and a micrometre a second. The rounding moves a
position by half a millimetre at most."""


def _read_header(meta: dict, path: Path) -> tuple[TimeArray, type, dict]:
    """
    The epoch and the frame from the header of a trajectory file.

    Parameters
    ----------
    meta : dict
        The header's metadata
    path : Path
        The file, for the error messages

    Returns
    -------
    epoch : Time
        The time the time column counts from, in the file's time scale
    frame_class : type
        The astropy frame of the states
    attributes : dict
        The frame's fixed attributes, such as an equinox

    Raises
    ------
    ValueError
        If a field is missing, or the time scale, the epoch or the frame is not
        understood
    """
    # The header must give the epoch, the time scale and the frame
    missing = [field for field in ("epoch", "time_scale", "frame") if field not in meta]
    if missing:
        raise ValueError(f"{path}: the header has no {', '.join(missing)}")
    # Time scale: any astropy scale except "local", which has no fixed meaning
    scale = str(meta["time_scale"]).strip().lower()
    # TIME_SCALES, not Time.SCALES: reading the class attribute leads pyright to
    # mistype every Time(...) call in the package
    if scale not in TIME_SCALES or scale == "local":
        raise ValueError(
            f"{path}: the time scale '{meta['time_scale']}' is not one of: "
            f"{', '.join(s for s in TIME_SCALES if s != 'local')}"
        )
    # The epoch is in the file's own time scale; the time column counts from it
    try:
        epoch = Time(meta["epoch"], scale=scale)
    except ValueError as error:
        raise ValueError(f"{path}: the epoch is not a time: {error}") from error
    try:
        frame_class, attributes = frame_of(meta["frame"])
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    return epoch, frame_class, attributes


def _read_columns(table: QTable, path: Path) -> dict[str, np.ndarray]:
    """
    The columns of a trajectory file, each in the unit of `COLUMNS`.

    Parameters
    ----------
    table : QTable
        The file, as astropy read it
    path : Path
        The file, for the error messages

    Returns
    -------
    values : dict
        Each column's values, by name

    Raises
    ------
    ValueError
        If a column is missing, has no unit, or has a unit of the wrong kind
    """
    # Check each required column exists, has a unit and is of the right kind,
    # then convert it to the unit the rest of the code expects
    values = {}
    for name, unit in COLUMNS.items():
        if name not in table.colnames:
            raise ValueError(f"{path}: there is no '{name}' column")
        column = table[name]
        if not isinstance(column, Quantity) or column.unit is None:
            raise ValueError(f"{path}: the '{name}' column has no unit")
        if not column.unit.is_equivalent(unit):
            raise ValueError(
                f"{path}: the '{name}' column is in {column.unit}, which is not a "
                f"unit of {unit.physical_type}"
            )
        values[name] = np.asarray(column.to_value(unit), dtype=float)
    return values


def read_ecsv_trajectory(path: str | Path) -> Trajectory:
    """
    Read a trajectory file in ECSV. See the module notes for the layout.

    Parameters
    ----------
    path : str | Path
        Filepath of the trajectory file

    Returns
    -------
    trajectory : Trajectory
        The trajectory, in GCRS

    Raises
    ------
    FileNotFoundError
        If the file does not exist
    ValueError
        If the file is not ECSV, lacks a column, a unit or a header field, gives
        a unit of the wrong kind or a frame that is not read, or if its times do
        not rise
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File does not exist: {path}")
    # QTable turns columns with units into Quantity columns
    try:
        table = QTable.read(path, format="ascii.ecsv")
    except Exception as error:
        raise ValueError(f"{path}: not an ECSV table: {error}") from error
    meta = dict(table.meta or {})
    epoch, frame_class, attributes = _read_header(meta, path)
    values = _read_columns(table, path)

    # Times are seconds after the epoch and must rise strictly
    offsets = values["time"]
    if np.any(np.diff(offsets) <= 0):
        raise ValueError(f"{path}: the times must rise, with no repeats")
    times = epoch + Q_(offsets, "s")
    # Position and velocity in km and km/s, in the file's frame
    data = CartesianRepresentation(
        Q_([values["x"], values["y"], values["z"]], "km"),
        differentials=CartesianDifferential(
            Q_([values["vx"], values["vy"], values["vz"]], "km/s")
        ),
    )
    state = SkyCoord(frame_class(data, obstime=times, **attributes))
    # The optional object name, then build the trajectory (this converts the
    # states to GCRS); its errors are reported with the file path
    name = meta.get("object_name")
    try:
        trajectory = Trajectory.from_states(
            state,
            name=None if name is None else str(name),
            frame=str(meta["frame"]),
        )
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    # Keep the file name and the format for display
    trajectory.file = path.name
    trajectory.format = "ECSV"
    return trajectory


def write_ecsv_trajectory(  # noqa: V103
    path: str | Path,
    state: SkyCoord,
    frame: str = "GCRS",
    name: str | None = None,
) -> Path:
    """
    Write states to a trajectory file in ECSV, as `read_ecsv_trajectory` reads it.

    Parameters
    ----------
    path : str | Path
        The file to write
    state : SkyCoord
        Positions with velocities, with an `obstime` for each, such as from
        `tle_states`
    frame : str, optional
        The frame to write the states in, one of
        `quicksat.orbit.trajectory.FRAMES`. GCRS by default.
    name : str, optional
        The name of the satellite, written as `object_name`

    Returns
    -------
    path : Path
        The file written. Its epoch is the first time, in UTC, to the
        millisecond. The values are rounded as `WRITTEN_DECIMALS` says.
    """
    path = Path(path)
    frame_class, attributes = frame_of(frame)
    times: TimeArray = state.obstime
    cartesian = state.transform_to(frame_class(obstime=times, **attributes)).cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    velocity = cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    # the epoch as the header writes it, to the millisecond, so that the times
    # count from exactly what is read back
    epoch = Time(times[0].utc.isot, scale="utc")
    meta = {"epoch": epoch.isot, "time_scale": "utc", "frame": frame.upper()}
    if name is not None:
        meta["object_name"] = name
    position, speed = cartesian.xyz, velocity.d_xyz
    values = {
        "time": times - epoch,
        "x": position[0],
        "y": position[1],
        "z": position[2],
        "vx": speed[0],
        "vy": speed[1],
        "vz": speed[2],
    }
    # plain columns with units keep the header short: a Quantity column would
    # add a block that says how to rebuild it
    table = Table(
        [
            Column(
                np.round(values[name].to_value(unit), WRITTEN_DECIMALS[name]),
                name=name,
                unit=unit,
            )
            for name, unit in COLUMNS.items()
        ],
        meta=meta,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    table.write(path, format="ascii.ecsv", overwrite=True)
    return path
