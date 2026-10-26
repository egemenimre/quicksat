# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The Scenario Editor: a web page that fills in and edits a scenario or power folder.

`write_editor` writes one page, which holds the folder's files as JSON, opens from disk
and saves the files again as downloads. The server can also serve it, with a button that
runs the files. quicksat's loaders check the files as the page is written, and the page
shows what they said. `decisions.md` 14 explains the page, and
`docs/guides/scenario/edit_and_view_a_scenario.md` how to use it.

"""

import base64
from pathlib import Path

from quicksat.editor.shared import (
    PAGE_FILE,
    build_page,
    csv_file,
    loader_check,
    vendor_text,
    yaml_file,
)
from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.scenario import SCENARIO_FILE
from quicksat.thermal import THERMAL_FILE

FORMAT = "quicksat-editor"
"""The `format` field of the data the page holds."""

VERSION = 1
"""The `version` field of the page's data, which stays the same in development."""


_ORBIT_FILES = ("tle_file", "omm_file", "trajectory_file")
"""The orbit's keys that name a file."""


SCRIPTS = (
    "elements.js",
    "project.js",
    "thermal.js",
    "sections.js",
    "checks.js",
    "write.js",
    "run.js",
    "designer.js",
    "view3d.js",
    "views.js",
)
"""The Scenario Editor's own scripts in `templates/scenario/`, in the order they run
after the shared ones."""


def _referenced(folder: Path, name) -> Path | None:
    """
    A file the scenario names, from its folder if relative, or None if none is named or
    it is missing.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    path = Path(name)
    path = path if path.is_absolute() else folder / path
    return path if path.is_file() else None


def _power_files(
    folder: Path,
    power_file: str,
    consumption_files: dict[str, str],
    thermal_file: str = THERMAL_FILE,
) -> tuple[dict, list[dict]]:
    """
    The power, consumption and thermal files as the page takes them, each None when
    missing, with the loaders' checks.
    """
    from quicksat.power.config import PowerSystem
    from quicksat.power.consumption import PowerConsumption
    from quicksat.thermal.config import PayloadThermal

    files: dict = {"power": None}
    checks = []
    power_path = folder / power_file
    if power_path.is_file():
        files["power"] = yaml_file(power_path)
        checks.append(
            loader_check(
                power_path.name, lambda: PowerSystem.from_yaml_file(power_path)
            )
        )
    for group, name in consumption_files.items():
        path = folder / name
        files[f"{group}_consumption"] = None
        if path.is_file():
            files[f"{group}_consumption"] = csv_file(path)
            checks.append(
                loader_check(
                    path.name, lambda path=path: PowerConsumption.from_csv(path)
                )
            )
    thermal_path = folder / thermal_file
    files["payload_thermal"] = None
    if thermal_path.is_file():
        files["payload_thermal"] = yaml_file(thermal_path)
        checks.append(
            loader_check(
                thermal_path.name, lambda: PayloadThermal.from_yaml_file(thermal_path)
            )
        )
    return files, checks


def editor_data(
    folder: str | Path,
    scenario_file: str = SCENARIO_FILE,
    power_file: str = POWER_FILE,
    consumption_files: dict[str, str] = CONSUMPTION_FILES,
    thermal_file: str = THERMAL_FILE,
) -> dict:
    """
    Everything the page needs from a folder of input files.

    Parameters
    ----------
    folder : str or Path
        The folder of input files
    scenario_file : str, optional
        The scenario file's name, which must exist
    power_file : str, optional
        The power system file's name, which may be missing
    consumption_files : dict of str to str, optional
        The consumption files' names by group, which may be missing
    thermal_file : str, optional
        The thermal file's name, which may be missing

    Returns
    -------
    data : dict
        The format and version, the folder's name and label, with no local path, the
        files, the model in base64, the orbit and target files as text, and the loaders'
        checks

    Raises
    ------
    FileNotFoundError
        If there is no scenario file
    """
    # here, so that the editor's imports stay light for the page alone
    from quicksat.scenario.config import Scenario

    folder = Path(folder)
    scenario_path = folder / scenario_file
    if not scenario_path.is_file():
        raise FileNotFoundError(f"no scenario file: {scenario_path}")
    scenario = yaml_file(scenario_path)
    checks = [
        loader_check(scenario_path.name, lambda: Scenario.from_yaml_file(scenario_path))
    ]
    raw = scenario["data"] if isinstance(scenario["data"], dict) else {}

    power_files, power_checks = _power_files(
        folder, power_file, consumption_files, thermal_file
    )
    checks += power_checks

    spacecraft = raw.get("3d_model")
    spacecraft = spacecraft.get("file") if isinstance(spacecraft, dict) else spacecraft
    model_path = _referenced(folder, spacecraft)
    model = None
    if model_path is not None:
        model = {
            "name": str(spacecraft),
            "glb_base64": base64.b64encode(model_path.read_bytes()).decode("ascii"),
        }

    orbit = raw.get("orbit")
    orbit = orbit if isinstance(orbit, dict) else {}
    orbit_file = None
    for key in _ORBIT_FILES:
        path = _referenced(folder, orbit.get(key))
        if path is not None:
            orbit_file = {"name": str(orbit[key]), "text": path.read_text("utf-8")}

    target_files = {}
    targets = raw.get("sat_targets")
    for target in (targets if isinstance(targets, dict) else {}).values():
        for key in _ORBIT_FILES:
            name = target.get(key) if isinstance(target, dict) else None
            path = _referenced(folder, name)
            if path is not None and str(name) not in target_files:
                target_files[str(name)] = path.read_text("utf-8")

    return {
        "format": FORMAT,
        "version": VERSION,
        "folder": folder.resolve().name,
        "label": folder.as_posix() if not folder.is_absolute() else folder.name,
        "files": {"scenario": scenario, **power_files},
        "model": model,
        "orbit_file": orbit_file,
        "target_files": [
            {"name": name, "text": text} for name, text in target_files.items()
        ],
        "checks": checks,
    }


def editor_page(data: dict) -> str:
    """
    The Scenario Editor's page, with three.js, uPlot and the folder's files.

    Parameters
    ----------
    data : dict
        The folder's files, from `editor_data`

    Returns
    -------
    page : str
        The page, as HTML
    """
    return build_page(
        "scenario",
        SCRIPTS,
        data,
        ("scenario", "power", "thermal"),
        **{
            "/*@three@*/": vendor_text("three.min.js"),
            "/*@uplot@*/": vendor_text("uPlot.iife.min.js"),
            "/*@uplot_css@*/": vendor_text("uPlot.min.css"),
        },
    )


def write_editor(
    folder: str | Path,
    output: str | Path,
    scenario_file: str = SCENARIO_FILE,
    power_file: str = POWER_FILE,
    consumption_files: dict[str, str] = CONSUMPTION_FILES,
    thermal_file: str = THERMAL_FILE,
) -> Path:
    """
    Write the editor page for a folder of input files, as they are now.

    Parameters
    ----------
    folder : str or Path
        The folder of input files
    output : str or Path
        The folder for the page, made if missing
    scenario_file, power_file, consumption_files, thermal_file : optional
        The files' names, if not the usual ones

    Returns
    -------
    page : Path
        The page, which opens in a browser
    """
    data = editor_data(
        folder, scenario_file, power_file, consumption_files, thermal_file
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    page = output / PAGE_FILE
    page.write_text(editor_page(data), encoding="utf-8")
    return page
