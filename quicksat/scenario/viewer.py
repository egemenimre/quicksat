# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The viewer of a scenario run: the page, and the data it shows.

The page opens from disk with no server, so `scenario.js` sets the data as a script,
model included. The JSON holds plain numbers, with units in the field names, vectors in
GCRS and times in s from `start`. It holds no time stamps, so the same inputs give the
same `id`. The Activity Designer shows the same page, sent by the editor's server: see
`designer_page`. `docs/scenario/scenario_ref.ipynb`, under "The viewer's data", explains
the fields.

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
from astropy.units import Quantity, UnitBase

from quicksat import R_EARTH, u
from quicksat.orbit.attitude import (
    body_rates,
    lvlh_rotations,
    quaternions,
    roll_pitch_yaw,
)
from quicksat.orbit.tle import Tle
from quicksat.scenario.attitude import SlewWindow, attitude_names, body_rotations
from quicksat.scenario.attitude_files import attitude_file_texts
from quicksat.scenario.events import STATUS_OK
from quicksat.scenario.names import GROUPS, PAYLOAD, PLATFORM, SLEW, UNPLANNED
from quicksat.scenario.plots import scenario_colours
from quicksat.scenario.run import ScenarioRun
from quicksat.scenario.spacecraft import node_index, read_glb_json
from quicksat.utils.intervals import TimeArray

FORMAT = "quicksat-scenario"
"""The `format` field of the scenario data."""

VERSION = 7
"""The `version` field of the scenario data. The page reads only this one, and it stays
the same in development."""

DATA_FILE = "scenario.js"
"""The name of the scenario data's file."""

PAGE_FILE = "scenario_viewer.html"
"""The viewer page's name in a scenario's folder."""

_PACKAGE = files("quicksat")
_TEMPLATES = _PACKAGE / "scenario" / "templates"
_VENDOR = _TEMPLATES / "vendor"

_DATA_TAGS = ('<script src="scenario.js"></script>', '<script src="power.js"></script>')
"""The template's tags that load the run's data, which `designer_page` replaces."""

_PAGE_PARTS = {
    "/*@uplot-css@*/": (_VENDOR / "uPlot.min.css", None),
    "/*@three@*/": (_VENDOR / "three.min.js", _VENDOR / "three.LICENSE"),
    "/*@uplot@*/": (_VENDOR / "uPlot.iife.min.js", _VENDOR / "uPlot.LICENSE"),
    "@coastlines@": (_PACKAGE / "data" / "coastlines.json", None),
    "/*@logic@*/": (_TEMPLATES / "viewer_logic.js", None),
}
"""Each placeholder in the template, the file that replaces it, and a library's licence
notice."""


def _flat(values: np.ndarray, decimals: int) -> list[float]:
    """Values rounded, as one flat list, row by row."""
    # adding zero turns -0.0 into 0.0
    return (np.round(values, decimals) + 0.0).ravel().tolist()


def _with_gaps(values: np.ndarray, decimals: int) -> list[float | None]:
    """Values rounded, as a list, with None for NaN, which the page draws as a gap."""
    rounded = np.round(values, decimals)
    return [None if np.isnan(value) else float(value) for value in rounded]


def _attitude_data(
    run: ScenarioRun,
    rotations: np.ndarray,
    position: np.ndarray,
    velocity: np.ndarray,
    designer: bool = False,
) -> dict:
    """
    The Attitude tab's data: the roll, pitch and yaw against LVLH, the turn rates and
    their limits, and the attitude files. The designer's leaves out the angles and the
    files.
    """
    n = len(rotations)
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
    shown = {"roll_deg": None, "pitch_deg": None, "yaw_deg": None, "files": None}
    if not designer:
        angles = roll_pitch_yaw(rotations, lvlh_rotations(position, velocity))
        angles = np.degrees(angles)
        shown = {
            "roll_deg": _flat(angles[:, 0], 3),
            "pitch_deg": _flat(angles[:, 1], 3),
            "yaw_deg": _flat(angles[:, 2], 3),
            "files": attitude_file_texts(run),
        }
    return {
        "roll_deg": shown["roll_deg"],
        "pitch_deg": shown["pitch_deg"],
        "yaw_deg": shown["yaw_deg"],
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
        "files": shown["files"],
    }


def _slew_ends(run: ScenarioRun) -> list[tuple[SlewWindow, TimeArray]]:
    """Each slew, and the end of its piece of the attitude track."""
    ends = []
    for index, window in enumerate(run.slews):
        end: TimeArray = window.end
        if index + 1 < len(run.slews) and run.slews[index + 1].start < end:
            end = run.slews[index + 1].start
        ends.append((window, end))
    return ends


def _attitudes_between_slews(run: ScenarioRun) -> P.IntervalDict:
    """
    The attitude of the activity under way, with the slews cut out, and `unplanned`
    after the last.
    """
    row = P.IntervalDict()
    for occurrence in run.occurrences:
        row[occurrence.interval] = occurrence.activity.attitude
    row[run.unplanned] = UNPLANNED
    for window in run.slews:
        del row[window.interval]
    return row


def _model_data(run: ScenarioRun, designer: bool = False) -> dict | None:
    """
    The 3D model as the page reads it, with its articulations, or None for a 1 m cube.
    The designer's leaves out the bytes and the angles.
    """
    model = run.scenario.spacecraft_model
    if model is None:
        return None
    gltf = read_glb_json(model.file)
    angles = {} if designer else run.articulations
    glb = None if designer else base64.b64encode(model.file.read_bytes())
    return {
        "name": model.file.name,
        "glb_base64": None if glb is None else glb.decode("ascii"),
        "articulations": [
            {
                "name": name,
                "part": articulation.part,
                "node": node_index(gltf, articulation.part),
                "axis": articulation.axis,
                "park_modes": sorted(articulation.park),
                "angle_deg": (
                    None
                    if designer
                    else _flat(np.asarray(angles[name].to_value(u.deg)), 3)
                ),
            }
            for name, articulation in model.articulations.items()
        ],
    }


def _orbit_file(run: ScenarioRun) -> dict:
    """The orbit file's name and text, or None for a sun-synchronous orbit."""
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
    The targets as the page draws them, the targets' files, and which attitudes and
    articulations point at each.
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
    Where the run's orbit comes from: its name and period, and its TLE lines or its
    trajectory's details.
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


def _tracks_data(
    run: ScenarioRun, seconds: Callable[[TimeArray], float]
) -> dict[str, list[dict]]:
    """The Gantt chart's pieces, in time order, with each slew a piece of its own."""
    tracks = {}
    for name, row in (
        ("illumination", run.illumination),
        ("attitude", _attitudes_between_slews(run)),
        ("payload_mode", run.mode[PAYLOAD]),
        ("platform_mode", run.mode[PLATFORM]),
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
    return {
        name: sorted(pieces, key=lambda piece: piece["start_s"])
        for name, pieces in tracks.items()
    }


def _occurrences_data(
    run: ScenarioRun, seconds: Callable[[TimeArray], float]
) -> list[dict]:
    """The activity table, one row per occurrence."""
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
                "mode": {group: activity.mode[group] for group in GROUPS},
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
    return occurrences


def _grid_data(
    run: ScenarioRun,
    position: np.ndarray,
    velocity: np.ndarray,
    rotations: np.ndarray,
    designer: bool,
) -> dict:
    """
    The values at each time step: the times, the states, the sun, the ground track, the
    beta angle, the light and the quaternions.
    """
    towards_sun = run.sun.xyz.to_value(u.km).T - position
    towards_sun /= np.linalg.norm(towards_sun, axis=1, keepdims=True)
    return {
        "t_s": _flat((run.times - run.times[0]).to_value(u.s), 3),
        "r_km": _flat(position, 3),
        "v_km_s": _flat(velocity, 6),
        "sun": _flat(towards_sun, 6),
        "lat_deg": _flat(run.latitude.to(u.deg).value, 4),
        "lon_deg": _flat(run.longitude.to(u.deg).value, 4),
        "beta_deg": _flat(run.beta.to(u.deg).value, 4),
        "light": _flat(run.light, 6),
        "q_body": None if designer else _flat(quaternions(rotations), 6),
        "q_earth": _flat(quaternions(run.grid.earth_rotations), 6),
    }


def scenario_data(run: ScenarioRun, designer: bool = False) -> dict:
    """
    Everything the viewer shows of a run, as plain numbers and text.

    Parameters
    ----------
    run : ScenarioRun
        The run
    designer : bool, optional
        Whether the data is for the Activity Designer, without what only the 3D views
        and the Attitude tab show

    Returns
    -------
    data : dict
        The fields of `scenario.js`, with `id`, the first 16 hex digits of the other
        fields' SHA-256

    Raises
    ------
    ValueError
        If part of a run for the normal viewer is `unplanned`
    """
    if not designer:
        run.check_planned("the viewer's data")
    start: TimeArray = run.times[0]

    def seconds(time: TimeArray) -> float:
        return round(float((time - start).to_value(u.s)), 3)

    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    differential = cartesian.differentials["s"]
    assert isinstance(differential, CartesianDifferential)
    position = cartesian.xyz.to_value(u.km).T
    velocity = differential.d_xyz.to_value(u.km / u.s).T
    rotations = body_rotations(run)

    source = run.scenario.source_file
    content = {
        "scenario_file": None if source is None else source.name,
        "scenario_text": run.scenario.source_text,
        **_orbit_file(run),
        "start": start.utc.isot,
        "earth_radius_km": R_EARTH.to_value(u.km),
        "orbit": _orbit_data(run),
        "colours": scenario_colours(run.scenario),
        "model": _model_data(run, designer),
        "grid": _grid_data(run, position, velocity, rotations, designer),
        "tracks": _tracks_data(run, seconds),
        "occurrences": _occurrences_data(run, seconds),
        **_targets_data(run, seconds),
        "warnings": run.warnings,
        "orbit_warnings": run.orbit_warnings,
        "attitude": _attitude_data(run, rotations, position, velocity, designer),
    }
    if designer:
        length = run.pass_length
        content["designer"] = {
            "repeat": run.repeat,
            "pass_s": None if length is None else round(float(length.value), 3),
        }
    header = {"format": FORMAT, "version": VERSION}
    text = json.dumps(header | content, allow_nan=False, separators=(",", ":"))
    data_id = hashlib.sha256(text.encode()).hexdigest()[:16]
    return header | {"id": data_id} | content


def _most(values: list[Quantity], unit: UnitBase, decimals: int) -> float | None:
    """The largest of some quantities in a unit, rounded, or None."""
    if not values:
        return None
    return round(max(float(value.to(unit).value) for value in values), decimals)


def activity_rows(run: ScenarioRun) -> list[dict]:
    """
    The results of each activity of the list, as the Activity Designer shows them beside
    it.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    rows : list of dict
        One per activity, in order: its count, its statuses, its longest time outside,
        its longest slew, and its rate excesses
    """
    rows = []
    for number in range(1, len(run.scenario.activities) + 1):
        occurrences = [o for o in run.occurrences if o.number == number]
        statuses: dict[str, int] = {}
        for occurrence in occurrences:
            for status in occurrence.statuses:
                if status != STATUS_OK:
                    statuses[status] = statuses.get(status, 0) + 1
        outside = [o.outside for o in occurrences if o.outside is not None]
        slews = [o.slew for o in occurrences if o.slew is not None]
        excesses = [e for e in run.rate_excesses if e.occurrence.number == number]
        rows.append(
            {
                "number": number,
                "count": len(occurrences),
                "statuses": statuses,
                "outside_s": _most(outside, u.s, 3),
                "slew_s": _most(slews, u.s, 3),
                "excesses": len(excesses),
                "peak_rate_deg_s": _most(
                    [e.peak_rate for e in excesses], u.deg / u.s, 5
                ),
                "peak_acceleration_deg_s2": _most(
                    [e.peak_acceleration for e in excesses], u.deg / u.s**2, 6
                ),
            }
        )
    return rows


def write_data_js(path: Path, key: str, data: dict, source: str) -> Path:
    """
    Write one of the viewer's data files, which sets `window.quicksat[key]`.

    Parameters
    ----------
    path : Path
        The file, such as `scenario.js`, its folder made if missing
    key : str
        The data's key, such as `scenario`
    data : dict
        The data, with no NaN
    source : str
        The input file, for the first line

    Returns
    -------
    path : Path
        The file written
    """
    text = (
        f"// Written by quicksat from {source}. Rerun the notebook instead of "
        "editing this file.\n"
        "window.quicksat = window.quicksat || {};\n"
        f"window.quicksat.{key} = "
        + json.dumps(data, allow_nan=False, separators=(",", ":"))
        + ";\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_scenario_js(
    run: ScenarioRun, folder: str | Path, data: dict | None = None
) -> Path:
    """
    Write the viewer's data for a run, as `scenario.js` in a folder.

    Parameters
    ----------
    run : ScenarioRun
        The run
    folder : str or Path
        The folder, made if missing
    data : dict, optional
        The run's data, if already worked out

    Returns
    -------
    path : Path
        The file written
    """
    data = data if data is not None else scenario_data(run)
    source = data["scenario_file"] or "a scenario"
    return write_data_js(Path(folder) / DATA_FILE, "scenario", data, source)


def viewer_page() -> str:
    """
    The viewer page, built from its template with its libraries, the coastlines and its
    logic inside.

    Returns
    -------
    page : str
        The page, as HTML

    Raises
    ------
    ValueError
        If a placeholder is missing or doubled, or a file would end its script tag early
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


def designer_page(data: dict) -> str:
    """
    The viewer page with a run's data inside, as the Activity Designer shows it.

    Parameters
    ----------
    data : dict
        The run's data, from `scenario_data` with `designer`

    Returns
    -------
    page : str
        The page, as HTML

    Raises
    ------
    ValueError
        If the template does not load each data file once
    """
    page = viewer_page()
    # every < of the JSON is inside a string, where \u003c is the same
    # character, so no text from the scenario file can end the script early
    text = json.dumps(data, allow_nan=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c")
    script = f"<script>window.quicksat = {{scenario: {text}}};</script>"
    for tag, replacement in zip(_DATA_TAGS, (script, ""), strict=True):
        if page.count(tag) != 1:
            raise ValueError(f"{tag} must appear once in the viewer template")
        page = page.replace(tag, replacement)
    return page


def write_scenario_viewer(run: ScenarioRun, folder: str | Path) -> Path:  # noqa: V103
    """
    Write the viewer for a run, the page and `scenario.js`, in a folder.

    Parameters
    ----------
    run : ScenarioRun
        The run
    folder : str or Path
        The folder, made if missing

    Returns
    -------
    page : Path
        The page, which opens in a browser
    """
    write_scenario_js(run, folder)
    page = Path(folder) / PAGE_FILE
    page.write_text(viewer_page(), encoding="utf-8")
    return page
