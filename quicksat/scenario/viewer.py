# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The data the viewer shows: a scenario run, written as `scenario.js`.

The viewer is a web page that opens from a file on disk, with no server. Such a
page cannot read a JSON file next to it, but it can load a script. So the data
is JSON with one assignment in front:

    window.quicksat = window.quicksat || {};
    window.quicksat.scenario = {...};

The JSON holds plain numbers. Units are in the field names: `_s`, `_km`,
`_km_s` and `_deg`. Every vector is in GCRS. Every time is in seconds from
`start`, rounded to 1 ms. A quaternion is `[x, y, z, w]`, scalar last.

The file holds no time stamps. So the same inputs and the same code write the
same bytes, and the `id` stays the same.

"""

import hashlib
import json
from pathlib import Path

import numpy as np
from astropy.coordinates import CartesianDifferential, CartesianRepresentation

from quicksat import R_EARTH, u
from quicksat.orbit.attitude import quaternions
from quicksat.orbit.geometry import earth_rotations
from quicksat.scenario.attitude import body_rotations
from quicksat.scenario.plots import scenario_colours
from quicksat.scenario.run import ScenarioRun
from quicksat.utils.intervals import TimeArray

FORMAT = "quicksat-scenario"
"""The `format` field of the scenario data."""

VERSION = 1
"""The `version` field of the scenario data. It goes up when a field changes."""

DATA_FILE = "scenario.js"
"""Name of the file the scenario data is written to."""


def _flat(values: np.ndarray, decimals: int) -> list[float]:
    """
    Values rounded, as one flat list: `x0, y0, z0, x1, ...` for vectors.

    Parameters
    ----------
    values : ndarray
        Values of any shape
    decimals : int
        The number of decimals to keep

    Returns
    -------
    flat : list of float
        The rounded values, row by row
    """
    return np.round(values, decimals).ravel().tolist()


def scenario_data(run: ScenarioRun) -> dict:
    """
    Everything the viewer shows of a run, as plain numbers and text.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    data : dict
        The fields of `scenario.js`. `grid` holds the values at each time step.
        `tracks` holds the three rows of the Gantt chart, and `occurrences` the
        activity table. `id` is the first 16 hex digits of the SHA-256 of the
        JSON text of the other fields.
    """
    start: TimeArray = run.times[0]

    def seconds(time: TimeArray) -> float:
        return round(float((time - start).to_value(u.s)), 3)

    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    velocity = cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    position = cartesian.xyz.to_value(u.km).T
    towards_sun = run.sun.xyz.to_value(u.km).T - position
    towards_sun /= np.linalg.norm(towards_sun, axis=1, keepdims=True)

    tracks = {}
    for name, row in (
        ("illumination", run.illumination),
        ("attitude", run.attitude),
        ("mode", run.mode),
    ):
        pieces = [
            {
                "value": value,
                "start_s": seconds(piece.lower),
                "end_s": seconds(piece.upper),
            }
            for interval, value in row.items()
            for piece in interval
        ]
        tracks[name] = sorted(pieces, key=lambda piece: piece["start_s"])

    occurrences = []
    for occurrence in run.occurrences:
        activity = occurrence.activity
        outside = occurrence.outside
        occurrences.append(
            {
                "repeat": occurrence.repeat,
                "number": occurrence.number,
                "start_s": seconds(occurrence.start),
                "end_s": seconds(occurrence.end),
                "trigger": activity.trigger.text,
                "attitude": activity.attitude,
                "mode": activity.mode,
                "constraint": activity.constraint,
                "outside_s": (
                    None if outside is None else round(float(outside.to(u.s).value), 3)
                ),
                "statuses": occurrence.statuses,
            }
        )

    source = run.scenario.source_file
    content = {
        "scenario_file": None if source is None else source.name,
        "scenario_text": run.scenario.source_text,
        "start": start.utc.isot,
        "earth_radius_km": R_EARTH.to_value(u.km),
        "orbit": {
            "name": run.tle.name,
            "tle": list(run.tle.lines),
            "nodal_period_s": round(float(run.tle.nodal_period.to(u.s).value), 3),
        },
        "colours": scenario_colours(run.scenario),
        "grid": {
            "t_s": _flat((run.times - start).to_value(u.s), 3),
            "r_km": _flat(position, 3),
            "v_km_s": _flat(velocity.d_xyz.to_value(u.km / u.s).T, 6),
            "sun": _flat(towards_sun, 6),
            "lat_deg": _flat(run.latitude.to(u.deg).value, 4),
            "lon_deg": _flat(run.longitude.to(u.deg).value, 4),
            "beta_deg": _flat(run.beta.to(u.deg).value, 4),
            "q_body": _flat(quaternions(body_rotations(run)), 6),
            "q_earth": _flat(quaternions(earth_rotations(run.times)), 6),
        },
        "tracks": tracks,
        "occurrences": occurrences,
    }
    header = {"format": FORMAT, "version": VERSION}
    text = json.dumps(header | content, allow_nan=False, separators=(",", ":"))
    data_id = hashlib.sha256(text.encode()).hexdigest()[:16]
    return header | {"id": data_id} | content


def write_scenario_js(run: ScenarioRun, folder: str | Path) -> Path:  # noqa: V103
    """
    Write the viewer's data for a run, as `scenario.js` in a folder.

    The folder is made if it does not exist, and an older `scenario.js` in it is
    replaced.

    Parameters
    ----------
    run : ScenarioRun
        The run
    folder : str | Path
        The folder to write to

    Returns
    -------
    path : Path
        The file written
    """
    data = scenario_data(run)
    source = data["scenario_file"] or "a scenario"
    text = (
        f"// Written by quicksat from {source}. Rerun the notebook instead of "
        "editing this file.\n"
        "window.quicksat = window.quicksat || {};\n"
        "window.quicksat.scenario = "
        + json.dumps(data, allow_nan=False, separators=(",", ":"))
        + ";\n"
    )
    path = Path(folder) / DATA_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path
