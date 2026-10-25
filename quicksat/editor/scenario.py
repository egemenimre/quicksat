# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The Scenario Editor: a web page that fills in and edits a scenario or power
folder.

The folder holds a scenario file and, if it is a power folder, a power system
file and the payload's and the platform's consumption files, with the 3D model
and any orbit file they name. A power folder may also hold the payload's thermal
file.
`write_editor` writes one page for it. The page opens from disk with a
double-click, and needs no Python and no server. `quicksat.editor.server` can
also serve the page from this computer. Its page then has a button that runs the
files and writes the viewer.

The page holds the folder's files inside itself. Python reads them here and
passes them to the page as JSON: each YAML file as YAML reads it, each CSV as
rows of text, the 3D model in base64, and an orbit file as text. The page turns them
into its own fields. The user can also open another folder, or one file, in the
page, which reads them in the same form. When the user saves, the page writes
the files again, as downloads: one by one, or as a zip.

Saving rewrites each file. The user's notes survive in the `comments` fields,
which every block of a file has. A `#` comment does not survive: the page writes
its own help as `#` lines, and replaces the rest. So `comment_blocks`, in
`quicksat.editor.shared`, finds every `#` comment, with the key it belongs to.

When the page is written, quicksat also reads the files with its own loaders.
The page shows what they said, because its own checks cover names, units and
ranges only.

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
"""The `version` field of the data the page holds. It stays the same during
development, even when a field changes. It goes up only once older pages must
still be read."""


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
"""The scenario editor's own scripts in `templates/scenario/`, in the order they
run after the shared ones."""


def _referenced(folder: Path, name) -> Path | None:
    """
    A file that the scenario names, taken from the folder if relative.

    Parameters
    ----------
    folder : Path
        The scenario file's folder
    name
        The name as the file gives it, or None

    Returns
    -------
    path : Path or None
        The file, or None if no file is named or it does not exist
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
    The power system file, the consumption files and the thermal file, as the
    page takes them.

    Parameters
    ----------
    folder : Path
        The folder that holds the files
    power_file : str
        The power system file's name
    consumption_files : dict of str to str
        The consumption files' names, by the group's name
    thermal_file : str, optional
        The payload's thermal file's name

    Returns
    -------
    files : dict
        `power`, `payload_consumption`, `platform_consumption` and
        `payload_thermal`, each None when missing
    checks : list of dict
        What quicksat's loaders said of each file there
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
    folder : str | Path
        The folder that holds the files
    scenario_file : str, optional
        The scenario file's name. It must exist.
    power_file : str, optional
        The power system file's name. It may be missing, as in a scenario folder.
    consumption_files : dict of str to str, optional
        The consumption files' names, by the group's name, `payload` and
        `platform`. Either may be missing, as in a scenario folder.
    thermal_file : str, optional
        The payload's thermal file's name. It may be missing.

    Returns
    -------
    data : dict
        `format`, `version` and `folder`, the folder's name. `label`, the
        folder as given when relative, such as `sample/power/data`, and its name
        otherwise, so that no local path goes into the page. `files`, with
        `scenario`, `power`, `payload_consumption`, `platform_consumption` and
        `payload_thermal`, each None when missing. `model`,
        the 3D model in base64, and `orbit_file`, an orbit file as text, each
        None without one. `target_files`, the files that the satellite targets
        name, as text, once each, each with its `name` as the scenario gives it.
        `checks`, what quicksat's loaders said of each file.

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
    The scenario editor's page, with three.js, uPlot and the folder's files.

    Parameters
    ----------
    data : dict
        The folder's files, from `editor_data`

    Returns
    -------
    page : str
        The page, as HTML text. uPlot draws the Thermal tab's plot.
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
    Write the editor page for a folder of input files.

    The page holds the files as they are now. To edit them again after they
    change on disk, write the page again.

    Parameters
    ----------
    folder : str | Path
        The folder that holds the input files
    output : str | Path
        The folder to write the page in. It is made if it does not exist.
    scenario_file, power_file, consumption_files, thermal_file : optional
        The files' names, if not the usual ones. See `editor_data`.

    Returns
    -------
    page : Path
        The page written. Double-click it to open the editor.
    """
    data = editor_data(
        folder, scenario_file, power_file, consumption_files, thermal_file
    )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    page = output / PAGE_FILE
    page.write_text(editor_page(data), encoding="utf-8")
    return page
