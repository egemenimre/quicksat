# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The viewer of a scenario run: the page, and the data it shows.

The viewer is a web page that opens from a file on disk, with no server. A
folder holds the page, `scenario_viewer.html`, and its data, `scenario.js`.
`write_scenario_viewer` writes both.

The page is the same for every run. Its source is the template
`quicksat/scenario/templates/viewer.html`. `viewer_page` puts the libraries
from `templates/vendor/` and the coastlines from `quicksat/data/` into it, so
the page needs nothing else to open.

A page opened from disk cannot read a JSON file next to it, but it can load a
script. So the data is JSON with one assignment in front:

    window.quicksat = window.quicksat || {};
    window.quicksat.scenario = {...};

The JSON holds plain numbers. Units are in the field names: `_s`, `_km`,
`_km_s` and `_deg`. Every vector is in GCRS. Every time is in seconds from
`start`, rounded to 1 ms. A quaternion is `[x, y, z, w]`, scalar last.

The spacecraft's 3D model travels inside `scenario.js` too, as the bytes of its
GLB file in base64. The page cannot read the `.glb` file from disk, for the
same reason it cannot read JSON.

The file holds no time stamps. So the same inputs and the same code write the
same bytes, and the `id` stays the same.

"""

import base64
import hashlib
import json
from importlib.resources import files
from pathlib import Path

import numpy as np
import portion as P
from astropy.coordinates import CartesianDifferential, CartesianRepresentation

from quicksat import R_EARTH, u
from quicksat.orbit.attitude import quaternions
from quicksat.orbit.geometry import earth_rotations
from quicksat.scenario.attitude import SLEW, SlewWindow, body_rotations
from quicksat.scenario.plots import scenario_colours
from quicksat.scenario.run import ScenarioRun
from quicksat.utils.intervals import TimeArray

FORMAT = "quicksat-scenario"
"""The `format` field of the scenario data."""

VERSION = 3
"""The `version` field of the scenario data. It goes up when a field changes.
Version 2 added `light` to the grid, and `penumbra` and `umbra` to the
illumination track, in place of `eclipse`. Version 3 added `model`, the
spacecraft's 3D model."""

DATA_FILE = "scenario.js"
"""Name of the file the scenario data is written to."""

PAGE_FILE = "scenario_viewer.html"
"""Name the viewer page takes in a scenario's folder."""

_PACKAGE = files("quicksat")
_TEMPLATES = _PACKAGE / "scenario" / "templates"
_VENDOR = _TEMPLATES / "vendor"

_PAGE_PARTS = {
    "/*@uplot-css@*/": (_VENDOR / "uPlot.min.css", None),
    "/*@three@*/": (_VENDOR / "three.min.js", _VENDOR / "three.LICENSE"),
    "/*@uplot@*/": (_VENDOR / "uPlot.iife.min.js", _VENDOR / "uPlot.LICENSE"),
    "@coastlines@": (_PACKAGE / "data" / "coastlines.json", None),
}
"""Each placeholder in the template, the file that replaces it, and the licence
notice that goes in front of a library."""


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


def _slew_ends(run: ScenarioRun) -> list[tuple[SlewWindow, TimeArray]]:
    """
    Each slew, and when it ends on the attitude track.

    A slew ends as its activity starts, unless the next slew starts first. That
    happens when the next activity is shorter than its slew.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    slews : list of tuple
        Each slew, and the end of its piece of the track
    """
    ends = []
    for index, window in enumerate(run.slews):
        end: TimeArray = window.end
        if index + 1 < len(run.slews) and run.slews[index + 1].start < end:
            end = run.slews[index + 1].start
        ends.append((window, end))
    return ends


def _attitudes_between_slews(run: ScenarioRun) -> P.IntervalDict:
    """
    The attitude of the activity under way, outside the slews.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    row : portion.IntervalDict
        Time intervals mapped to attitude names, with the slews cut out
    """
    row = P.IntervalDict()
    for occurrence in run.occurrences:
        row[occurrence.interval] = occurrence.activity.attitude
    for window in run.slews:
        del row[window.interval]
    return row


def _model_data(path: Path | None) -> dict | None:
    """
    The spacecraft's 3D model, as the page reads it.

    Parameters
    ----------
    path : Path or None
        The GLB file, or None for no model

    Returns
    -------
    model : dict or None
        `name`, the file name, and `glb_base64`, the file's bytes in base64. None
        without a model, for which the page draws a 1 m cube.
    """
    if path is None:
        return None
    return {
        "name": path.name,
        "glb_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


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
        activity table. `model` holds the spacecraft's 3D model, or None. `id` is the first 16 hex digits of the SHA-256 of the
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
        ("attitude", _attitudes_between_slews(run)),
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
        tracks[name] = pieces
    # each slew is a piece of its own, which names the attitude it turns into
    tracks["attitude"] += [
        {
            "value": SLEW,
            "target": window.target,
            "start_s": seconds(window.start),
            "end_s": seconds(end),
        }
        for window, end in _slew_ends(run)
    ]
    for name, pieces in tracks.items():
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
                "slew_s": (
                    None
                    if occurrence.slew is None
                    else round(float(occurrence.slew.to(u.s).value), 3)
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
        "model": _model_data(run.scenario.spacecraft_model),
        "grid": {
            "t_s": _flat((run.times - start).to_value(u.s), 3),
            "r_km": _flat(position, 3),
            "v_km_s": _flat(velocity.d_xyz.to_value(u.km / u.s).T, 6),
            "sun": _flat(towards_sun, 6),
            "lat_deg": _flat(run.latitude.to(u.deg).value, 4),
            "lon_deg": _flat(run.longitude.to(u.deg).value, 4),
            "beta_deg": _flat(run.beta.to(u.deg).value, 4),
            "light": _flat(run.light, 6),
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


def write_scenario_js(run: ScenarioRun, folder: str | Path) -> Path:
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


def viewer_page() -> str:
    """
    The viewer page, built from its template with everything it needs inside.

    Each placeholder in `templates/viewer.html` is replaced by a file: the
    three.js and uPlot libraries, uPlot's stylesheet, and the coastlines. Each
    library's MIT licence notice goes in front of it, as a comment.

    Returns
    -------
    page : str
        The page, as HTML text

    Raises
    ------
    ValueError
        If a placeholder is missing from the template or appears twice, or if a
        file holds text that would end its script tag early
    """
    page = (_TEMPLATES / "viewer.html").read_text(encoding="utf-8")
    for placeholder, (source, notice) in _PAGE_PARTS.items():
        if page.count(placeholder) != 1:
            raise ValueError(f"{placeholder} must appear once in the viewer template")
        text = source.read_text(encoding="utf-8")
        if notice is not None:
            text = f"/*!\n{notice.read_text(encoding='utf-8')}*/\n{text}"
        if "</script" in text.lower():
            raise ValueError(f"{source.name} holds '</script', which ends its tag")
        page = page.replace(placeholder, text)
    return page


def write_scenario_viewer(run: ScenarioRun, folder: str | Path) -> Path:  # noqa: V103
    """
    Write the viewer for a run: the page and `scenario.js`, in a folder.

    The page is built from its template with `viewer_page`, as
    `scenario_viewer.html`. So a change to the template reaches the folder on the
    next run. The folder is made if it does not exist, and older files are
    replaced.

    Parameters
    ----------
    run : ScenarioRun
        The run
    folder : str | Path
        The folder to write to

    Returns
    -------
    page : Path
        The page written. Double-click it to open the viewer.
    """
    write_scenario_js(run, folder)
    page = Path(folder) / PAGE_FILE
    page.write_text(viewer_page(), encoding="utf-8")
    return page
