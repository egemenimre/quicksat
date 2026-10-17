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
the page needs nothing else to open. It puts in `templates/viewer_logic.js` too:
the page's checks on its data and its values between grid steps, which the
tests in `tests/scenario/js/` run in Node.

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
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path

import numpy as np
import portion as P
from astropy.coordinates import CartesianDifferential, CartesianRepresentation

from quicksat import R_EARTH, u
from quicksat.orbit.attitude import (
    body_rates,
    lvlh_rotations,
    quaternions,
    roll_pitch_yaw,
)
from quicksat.orbit.geometry import earth_rotations
from quicksat.orbit.tle import Tle
from quicksat.scenario.attitude import SlewWindow, attitude_names, body_rotations
from quicksat.scenario.attitude_files import attitude_file_texts
from quicksat.scenario.config import SLEW
from quicksat.scenario.plots import scenario_colours
from quicksat.scenario.run import ScenarioRun
from quicksat.scenario.spacecraft import node_index, read_glb_json
from quicksat.utils.intervals import TimeArray

FORMAT = "quicksat-scenario"
"""The `format` field of the scenario data."""

VERSION = 7
"""The `version` field of the scenario data. The page reads only this version.
It stays the same during development, even when a field changes. It goes up
only once older files must still be read."""

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
    "/*@logic@*/": (_TEMPLATES / "viewer_logic.js", None),
}
"""Each placeholder in the template, the file that replaces it, and the licence
notice that goes in front of a library. `viewer_logic.js` is the page's own
logic that needs no browser, kept apart so that Node can test it."""


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
    # adding zero turns -0.0 into 0.0
    return (np.round(values, decimals) + 0.0).ravel().tolist()


def _with_gaps(values: np.ndarray, decimals: int) -> list[float | None]:
    """
    Values rounded, as a list, with None where a value is NaN.

    Parameters
    ----------
    values : ndarray
        Values, shape (n,)
    decimals : int
        The number of decimals to keep

    Returns
    -------
    values : list of float or None
        The rounded values. JSON has no NaN, and the page draws None as a gap.
    """
    rounded = np.round(values, decimals)
    return [None if np.isnan(value) else float(value) for value in rounded]


def _attitude_data(
    run: ScenarioRun, rotations: np.ndarray, position: np.ndarray, velocity: np.ndarray
) -> dict:
    """
    The body's attitude, as the page's Attitude tab shows it.

    Parameters
    ----------
    run : ScenarioRun
        The run
    rotations : ndarray
        The body's orientation at each time of the grid, from `body_rotations`
    position, velocity : ndarray
        The states in GCRS, in km and km/s, shape (n, 3)

    Returns
    -------
    attitude : dict
        `roll_deg`, `pitch_deg` and `yaw_deg` against LVLH, from
        `roll_pitch_yaw`. `rate_deg_s`, the turn rate over the step from each
        time, None at the last. `acceleration_deg_s2`, at each time between two
        steps, None at both ends. Both are None across an attitude change with no
        slew, which is instant. `max_rate_deg_s` and `max_acceleration_deg_s2`,
        the `slew` block's limits, or None. `files`, the text of each file of
        `attitude_file_texts`, by its name.
    """
    n = len(rotations)
    angles = np.degrees(roll_pitch_yaw(rotations, lvlh_rotations(position, velocity)))
    seconds = np.asarray((run.times - run.times[0]).to_value(u.s))
    rates, accelerations = body_rates(rotations, seconds)
    names = attitude_names(run)
    # an attitude change with no slew is instant, so it has no rate to show
    jumps = (names[1:] != names[:-1]) & (names[1:] != SLEW) & (names[:-1] != SLEW)
    rate = np.full(n, np.nan)
    rate[:-1] = np.where(jumps, np.nan, np.degrees(rates))
    acceleration = np.full(n, np.nan)
    acceleration[1:-1] = np.where(
        jumps[:-1] | jumps[1:], np.nan, np.degrees(accelerations)
    )
    slew = run.scenario.slew
    max_rate = None if slew is None else slew.max_rate
    max_acceleration = None if slew is None else slew.max_acceleration
    return {
        "roll_deg": _flat(angles[:, 0], 3),
        "pitch_deg": _flat(angles[:, 1], 3),
        "yaw_deg": _flat(angles[:, 2], 3),
        "rate_deg_s": _with_gaps(rate, 5),
        "acceleration_deg_s2": _with_gaps(acceleration, 6),
        "max_rate_deg_s": (
            None if max_rate is None else float(max_rate.to_value(u.deg / u.s))
        ),
        "max_acceleration_deg_s2": (
            None
            if max_acceleration is None
            else float(max_acceleration.to_value(u.deg / u.s**2))
        ),
        "files": attitude_file_texts(run),
    }


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


def _model_data(run: ScenarioRun) -> dict | None:
    """
    The spacecraft's 3D model, as the page reads it.

    Parameters
    ----------
    run : ScenarioRun
        The run, whose scenario may name a model

    Returns
    -------
    model : dict or None
        `name`, the file name, `glb_base64`, the file's bytes in base64, and
        `articulations`. Each articulation has its `name`, its `part`, the index
        of that `node` in the glTF, its `axis`, the `park_modes` it parks in, and
        `angle_deg`, its angle at each time of the grid. None without a model,
        for which the page draws a 1 m cube.
    """
    model = run.scenario.spacecraft_model
    if model is None:
        return None
    gltf = read_glb_json(model.file)
    angles = run.articulations
    return {
        "name": model.file.name,
        "glb_base64": base64.b64encode(model.file.read_bytes()).decode("ascii"),
        "articulations": [
            {
                "name": name,
                "part": articulation.part,
                "node": node_index(gltf, articulation.part),
                "axis": articulation.axis,
                "park_modes": sorted(articulation.park),
                "angle_deg": _flat(np.asarray(angles[name].to_value(u.deg)), 3),
            }
            for name, articulation in model.articulations.items()
        ],
    }


def _orbit_file(run: ScenarioRun) -> dict:
    """
    The file the orbit was read from, so that the viewer holds every input.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    file : dict
        `orbit_file` and `orbit_text`, the file's name and text. Both are None
        for a sun-synchronous orbit, which has no file.
    """
    source = run.scenario.orbit
    path = source.tle_file or source.omm_file or source.trajectory_file
    if path is None:
        return {"orbit_file": None, "orbit_text": None}
    return {"orbit_file": path.name, "orbit_text": path.read_text(encoding="utf-8")}


def _element_set_label(tle: Tle) -> str:
    """An element set's name and catalogue number, as the page shows them."""
    number = tle.satrec.satnum
    return f"{tle.name} ({number})" if tle.name else f"catalogue number {number}"


def _targets_data(run: ScenarioRun, seconds: Callable[[TimeArray], float]) -> dict:
    """
    The targets, as the page draws them: where each is, when it is in view, and
    where a satellite's orbit came from.

    Parameters
    ----------
    run : ScenarioRun
        The run
    seconds : callable
        Turns a time into seconds from the start of the run, to 1 ms

    Returns
    -------
    data : dict
        `targets`: each target, the ground ones first, with its `name`, its
        `kind`, `ground` or `satellite`, and its `passes`, each with `start_s`,
        `end_s` and `closest_km`, the closest range on the grid, or None. A
        ground target has its `latitude_deg`, `longitude_deg`, `altitude_km` and
        `min_elevation_deg`. A satellite has its `min_clearance_km`, its
        positions on the grid in GCRS, `r_km`, to 0.1 km, and its `source`: the
        `file`, then the `element_set` and its `epoch`, or the `start` and the
        `end` of the trajectory. `target_files`: the `name` and the `text` of
        each satellite target's file, once each. `pointing`: the targets that
        each attitude names, under `attitudes`, and that each articulation
        points at, under `articulations`.
    """
    scenario = run.scenario
    table = run.passes

    def passes(name: str) -> list[dict]:
        closest = table.loc[table["target"] == name, "closest [km]"].tolist()
        return [
            {
                "start_s": seconds(piece.lower),
                "end_s": seconds(piece.upper),
                "closest_km": None if np.isnan(near) else round(float(near), 1),
            }
            for piece, near in zip(run.in_view[name], closest, strict=True)
        ]

    targets = [
        {
            "name": name,
            "kind": "ground",
            "latitude_deg": float(ground.latitude.to_value(u.deg)),
            "longitude_deg": float(ground.longitude.to_value(u.deg)),
            "altitude_km": float(ground.altitude.to_value(u.km)),
            "min_elevation_deg": float(ground.min_elevation.to_value(u.deg)),
            "passes": passes(name),
        }
        for name, ground in scenario.gnd_targets.items()
    ]
    held: dict[Path, dict] = {}
    for name, target in scenario.sat_targets.items():
        orbit = run.sat_orbits[name]
        source: dict = {"file": target.file.name}
        if isinstance(orbit, Tle):
            source |= {
                "element_set": _element_set_label(orbit),
                "epoch": orbit.epoch.utc.isot,
            }
        else:
            source |= {"start": orbit.start.utc.isot, "end": orbit.end.utc.isot}
        cartesian = run.sat_states[name].cartesian
        assert isinstance(cartesian, CartesianRepresentation)
        targets.append(
            {
                "name": name,
                "kind": "satellite",
                "min_clearance_km": float(target.min_clearance.to_value(u.km)),
                "r_km": _flat(cartesian.xyz.to_value(u.km).T, 1),
                "source": source,
                "passes": passes(name),
            }
        )
        if target.file not in held:
            held[target.file] = {
                "name": target.file.name,
                "text": target.file.read_text(encoding="utf-8"),
            }
    names = set(scenario.gnd_targets) | set(scenario.sat_targets)
    attitudes = {
        name: used
        for name, attitude in scenario.attitudes.items()
        if (used := [d for d in dict.fromkeys(attitude.directions) if d in names])
    }
    model = scenario.spacecraft_model
    articulations = {
        name: articulation.point[1]
        for name, articulation in (model.articulations if model else {}).items()
        if articulation.point[1] in names
    }
    return {
        "targets": targets,
        "target_files": list(held.values()),
        "pointing": {"attitudes": attitudes, "articulations": articulations},
    }


def _orbit_data(run: ScenarioRun) -> dict:
    """
    Where the run's orbit comes from, as the page shows it.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    orbit : dict
        `name`, and `period_s`, the period a duration in orbits counts. Then
        either `tle`, the two TLE lines, or `trajectory`: the file, its format
        and frame, its samples and segments, who wrote it, its span in UTC and
        how its period was found. The other is None.
    """
    orbit = run.orbit
    data = {
        "name": orbit.name,
        "period_s": round(float(orbit.period.to(u.s).value), 3),
        "tle": None,
        "trajectory": None,
    }
    if isinstance(orbit, Tle):
        data["tle"] = list(orbit.lines)
    else:
        data["trajectory"] = {
            "file": orbit.file,
            "format": orbit.format,
            "frame": orbit.frame,
            "samples": orbit.sample_count,
            "segments": orbit.segment_count,
            "originator": orbit.originator,
            "start": orbit.start.utc.isot,
            "end": orbit.end.utc.isot,
            "period_from": orbit.period_method,
        }
    return data


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
        activity table. `model` holds the spacecraft's 3D model and the angles
        of its articulations, or None. `targets`, `target_files` and `pointing`
        come from `_targets_data`. `warnings` holds every warning of the run,
        and `orbit_warnings` those on the orbits alone. `id` is the first 16 hex
        digits of the SHA-256 of the JSON text of the other fields.
    """
    start: TimeArray = run.times[0]

    def seconds(time: TimeArray) -> float:
        return round(float((time - start).to_value(u.s)), 3)

    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    velocity = cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    position = cartesian.xyz.to_value(u.km).T
    rotations = body_rotations(run)
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
                "title": activity.title,
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
        **_orbit_file(run),
        "start": start.utc.isot,
        "earth_radius_km": R_EARTH.to_value(u.km),
        "orbit": _orbit_data(run),
        "colours": scenario_colours(run.scenario),
        "model": _model_data(run),
        "grid": {
            "t_s": _flat((run.times - start).to_value(u.s), 3),
            "r_km": _flat(position, 3),
            "v_km_s": _flat(velocity.d_xyz.to_value(u.km / u.s).T, 6),
            "sun": _flat(towards_sun, 6),
            "lat_deg": _flat(run.latitude.to(u.deg).value, 4),
            "lon_deg": _flat(run.longitude.to(u.deg).value, 4),
            "beta_deg": _flat(run.beta.to(u.deg).value, 4),
            "light": _flat(run.light, 6),
            "q_body": _flat(quaternions(rotations), 6),
            "q_earth": _flat(quaternions(earth_rotations(run.times)), 6),
        },
        "tracks": tracks,
        "occurrences": occurrences,
        **_targets_data(run, seconds),
        "warnings": run.warnings,
        "orbit_warnings": run.orbit_warnings,
        "attitude": _attitude_data(
            run, rotations, position, velocity.d_xyz.to_value(u.km / u.s).T
        ),
    }
    header = {"format": FORMAT, "version": VERSION}
    text = json.dumps(header | content, allow_nan=False, separators=(",", ":"))
    data_id = hashlib.sha256(text.encode()).hexdigest()[:16]
    return header | {"id": data_id} | content


def write_scenario_js(
    run: ScenarioRun, folder: str | Path, data: dict | None = None
) -> Path:
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
    data : dict, optional
        The run's data, from `scenario_data`, if it is already worked out. Power
        needs its `id` before writing `power.js`.

    Returns
    -------
    path : Path
        The file written
    """
    data = data if data is not None else scenario_data(run)
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
    three.js and uPlot libraries, uPlot's stylesheet, the coastlines, and the
    page's logic from `templates/viewer_logic.js`. Each library's MIT licence
    notice goes in front of it, as a comment.

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
