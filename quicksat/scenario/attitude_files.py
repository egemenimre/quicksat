# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The body's attitude and the articulations' angles, as ECSV files for other tools.

`attitude.ecsv` holds the time, the quaternion `qx qy qz qw` from body axes into GCRS,
scalar last, and the attitude in effect. Each `articulation_<name>.ecsv` holds the time,
the angle and whether the part is parked. The headers say what the numbers mean, and
hold no time stamps, so a run always writes the same bytes.
`docs/scenario/scenario_ref.ipynb`, under "The attitude files", shows them.

"""

import io
import re
from pathlib import Path

import numpy as np
from astropy.table import Column, Table
from astropy.time import Time

from quicksat import u
from quicksat.orbit.attitude import quaternions
from quicksat.scenario.articulation import grid_modes
from quicksat.scenario.attitude import attitude_names, body_rotations
from quicksat.scenario.names import PLATFORM
from quicksat.scenario.run import ScenarioRun

ATTITUDE_FILE = "attitude.ecsv"
"""The name of the body's attitude file."""

QUATERNION_DECIMALS = 9
"""The decimals kept in each part of a quaternion: under 1e-8 rad of turn."""

ANGLE_DECIMALS = 6
"""Decimals kept in an articulation's angle, in degrees."""

QUATERNION_NOTES = {
    "quaternion": (
        "qx, qy, qz, qw: the scalar part qw last, with Hamilton's product (i j = k)"
    ),
    "rotation": (
        "body to GCRS: v_gcrs = q v_body q*. Column i of its matrix is body axis i "
        "in GCRS."
    ),
    "scipy": "Rotation.from_quat([qx, qy, qz, qw]).apply(v_body) gives v_gcrs",
    "signs": (
        "q and -q are the same turn. Each row takes the sign nearer the row before, "
        "so rows interpolate."
    ),
    "jumps": (
        "Without a slew, an attitude change is instant: do not interpolate across it."
    ),
}
"""What the attitude file's header says about its quaternions, line by line."""


def _rounded(values: np.ndarray, decimals: int) -> np.ndarray:
    """Values rounded, with no -0.0."""
    return np.round(values, decimals) + 0.0


def _header(run: ScenarioRun) -> tuple[dict, np.ndarray]:
    """
    The metadata both kinds of file share, and each step's time since the epoch, in s,
    to the millisecond.
    """
    # the epoch as the header writes it, to the millisecond, so that the times
    # count from exactly what is read back
    epoch = Time(run.times[0].utc.isot, scale="utc")
    source = run.scenario.source_file
    meta = {} if source is None else {"scenario_file": source.name}
    meta |= {"epoch": epoch.isot, "time_scale": "utc"}
    return meta, _rounded((run.times - epoch).to_value(u.s), 3)


def _time_column(seconds: np.ndarray) -> Column:
    """The time column that both kinds of file start with."""
    return Column(seconds, name="time", unit=u.s, description="Time since the epoch")


def attitude_table(run: ScenarioRun) -> Table:
    """
    The body's attitude at each time of the run's grid, as a table.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    table : Table
        `time` in s, `qx`, `qy`, `qz`, `qw` and `attitude`, with the epoch, the time
        scale, the frame and `QUATERNION_NOTES` as metadata

    Raises
    ------
    ValueError
        If part of the run is `unplanned`
    """
    run.check_planned("the attitude file")
    meta, seconds = _header(run)
    q = _rounded(quaternions(body_rotations(run)), QUATERNION_DECIMALS)
    parts = {
        "qx": "x of the quaternion's vector part",
        "qy": "y of the quaternion's vector part",
        "qz": "z of the quaternion's vector part",
        "qw": "The quaternion's scalar part",
    }
    # plain columns keep the header short: a Quantity column would add a block
    # that says how to rebuild it
    columns = [_time_column(seconds)]
    columns += [
        Column(q[:, k], name=name, description=text)
        for k, (name, text) in enumerate(parts.items())
    ]
    columns.append(
        Column(
            attitude_names(run).astype(str),
            name="attitude",
            description="The attitude in effect, or slew",
        )
    )
    return Table(columns, meta=meta | {"frame": "GCRS"} | QUATERNION_NOTES)


def articulation_tables(run: ScenarioRun) -> dict[str, Table]:
    """
    Each articulation's angle at each time of the run's grid, as tables.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    tables : dict of str to Table
        By name: `time` in s, `angle` in degrees and `parked`
    """
    model = run.scenario.spacecraft_model
    if model is None or not model.articulations:
        return {}
    meta, seconds = _header(run)
    modes = grid_modes(run, PLATFORM)
    tables = {}
    for name, articulation in model.articulations.items():
        about = {
            "articulation": name,
            "part": articulation.part,
            "axis": articulation.axis,
            "point": list(articulation.point),
            "range": [f"{end.to_value(u.deg):g} deg" for end in articulation.range],
            "park": {
                mode: f"{angle.to_value(u.deg):g} deg"
                for mode, angle in articulation.park.items()
            },
            "angle": (
                "The turn about axis, right-handed. Zero is where the 3D model draws "
                "the part."
            ),
            "turn": (
                "The part turns about axis through its node's origin. attitude.ecsv "
                "turns the body into GCRS."
            ),
            "jumps": "Where parked changes, the part turns at once: do not interpolate.",
        }
        angles = run.articulations[name].to_value(u.deg)
        tables[name] = Table(
            [
                _time_column(seconds),
                Column(
                    _rounded(angles, ANGLE_DECIMALS),
                    name="angle",
                    unit=u.deg,
                    description="The turn about the drive axis",
                ),
                Column(
                    np.isin(modes, list(articulation.park)),
                    name="parked",
                    description="Held at the park angle of the platform's mode",
                ),
            ],
            meta=meta | about,
        )
    return tables


def articulation_file(name: str) -> str:
    """
    An articulation's file name, with each run of characters other than letters, digits,
    `+` and `-` as one `_`.

    Parameters
    ----------
    name : str
        The articulation's name, such as `wing +y`

    Returns
    -------
    file : str
        Such as `articulation_wing_+y.ecsv`
    """
    return "articulation_" + re.sub(r"[^\w+-]+", "_", name).strip("_") + ".ecsv"


def attitude_file_texts(run: ScenarioRun) -> dict[str, str]:
    """
    The text of each attitude file, by name, as the viewer offers and
    `write_attitude_files` writes them.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    texts : dict of str to str
        `attitude.ecsv` first, then each articulation's

    Raises
    ------
    ValueError
        If two articulations' names give the same file name
    """
    tables = {ATTITUDE_FILE: attitude_table(run)}
    for name, table in articulation_tables(run).items():
        file = articulation_file(name)
        if file in tables:
            raise ValueError(
                f"the articulations '{tables[file].meta['articulation']}' and "
                f"'{name}' would both be written to {file}: rename one of them"
            )
        tables[file] = table
    texts = {}
    for file, table in tables.items():
        buffer = io.StringIO()
        table.write(buffer, format="ascii.ecsv")
        texts[file] = buffer.getvalue()
    return texts


def write_attitude_files(run: ScenarioRun, folder: str | Path) -> list[Path]:
    """
    Write the body's attitude and each articulation's angles as ECSV files in a folder.

    Parameters
    ----------
    run : ScenarioRun
        The run
    folder : str or Path
        The folder, made if missing

    Returns
    -------
    paths : list of Path
        The files written

    Raises
    ------
    ValueError
        If two articulations' names give the same file name
    """
    texts = attitude_file_texts(run)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for file, text in texts.items():
        path = folder / file
        # no newline translation, so the file is the same on every system
        path.write_text(text, encoding="utf-8", newline="")
        paths.append(path)
    return paths
