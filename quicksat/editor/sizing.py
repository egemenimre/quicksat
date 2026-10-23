# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The sizing editor: a web page that fills in and edits a folder of sizing files.

A sizing folder holds `mission.yaml`, `requirements.yaml` and the files of the
budgets it sizes: the mass budget's settings and equipment list, the payload
data flow, the delta-V settings and manoeuvres, and the agility settings. Each
file has its usual name, as the sizing notebooks read them by name.

The page is made as the scenario editor's is, from the same shared parts. It is
a page of its own, because the sizing files share nothing with a scenario: their
orbit is a reference orbit, with no epoch and no node (`decisions.md` 9).

"""

from pathlib import Path

from quicksat.editor.editor import (
    PAGE_FILE,
    _check,
    _csv_file,
    _yaml_file,
    build_page,
)

FORMAT = "quicksat-sizing-editor"
"""The `format` field of the data the page holds."""

VERSION = 1
"""The `version` field of the data the page holds. It stays the same during
development, even when a field changes. It goes up only once older pages must
still be read."""

NAMES = {
    "mission": "mission.yaml",
    "requirements": "requirements.yaml",
    "mass": "mass_budget_config.yaml",
    "equipment": "equipment.csv",
    "data": "pl_dataflow_model.yaml",
    "deltav": "delta_v_config.yaml",
    "manoeuvres": "manoeuvres.csv",
    "agility": "agility_config.yaml",
}
"""Each sizing file's kind, as the page names it, and its usual name."""

SCRIPTS = (
    "project.js",
    "sections.js",
    "checks.js",
    "write.js",
    "budgets.js",
    "export.js",
    "views.js",
)
"""The sizing editor's own scripts in `templates/sizing/`, in the order they run
after the shared ones."""


def sizing_data(folder: str | Path) -> dict:
    """
    Everything the page needs from a folder of sizing files.

    Parameters
    ----------
    folder : str | Path
        The folder that holds the files. Any of them may be missing.

    Returns
    -------
    data : dict
        `format`, `version` and `folder`, the folder's name. `label`, the folder
        as given when relative, and its name otherwise, so that no local path
        goes into the page. `files`, each file by its kind, or None when it is
        missing. `checks`, what quicksat's loaders said of each budget's files.
        `results`, every budget as quicksat works it out now, from
        `budget_results`, for the Budgets tab.

    Raises
    ------
    FileNotFoundError
        If the folder holds none of the sizing files
    """
    # here, so that the editor's imports stay light for the page alone
    from quicksat.agility.budget import AgilityConfig
    from quicksat.dataflow.budget import DataFlowModel
    from quicksat.delta_v.budget import DeltaVBudget
    from quicksat.editor.budgets import budget_results
    from quicksat.mass.budget import MassBudget
    from quicksat.utils.mission import Mission
    from quicksat.utils.requirements import Requirements

    folder = Path(folder)
    paths = {kind: folder / name for kind, name in NAMES.items()}
    found = {kind: path for kind, path in paths.items() if path.is_file()}
    if not found:
        raise FileNotFoundError(f"no sizing file, such as mission.yaml: {folder}")
    files = {
        kind: (_csv_file(path) if path.suffix == ".csv" else _yaml_file(path))
        if kind in found
        else None
        for kind, path in paths.items()
    }

    name = NAMES
    checks = []
    if "mission" in found:
        checks.append(
            _check(name["mission"], lambda: Mission.from_yaml_file(paths["mission"]))
        )
    if "requirements" in found:
        checks.append(
            _check(
                name["requirements"],
                lambda: Requirements.from_yaml_file(paths["requirements"]),
            )
        )
    if {"mass", "equipment"} <= found.keys():
        checks.append(
            _check(
                f"{name['equipment']} with {name['mass']}",
                lambda: MassBudget.from_csv(paths["equipment"], paths["mass"]),
            )
        )
    if "data" in found:
        checks.append(
            _check(name["data"], lambda: DataFlowModel.from_yaml_file(paths["data"]))
        )
    if {"deltav", "manoeuvres", "mission"} <= found.keys():
        checks.append(
            _check(
                f"{name['manoeuvres']} with {name['deltav']}",
                lambda: DeltaVBudget.from_csv(
                    paths["manoeuvres"], paths["deltav"], paths["mission"]
                ),
            )
        )
    if "agility" in found:
        checks.append(
            _check(
                name["agility"], lambda: AgilityConfig.from_yaml_file(paths["agility"])
            )
        )

    return {
        "format": FORMAT,
        "version": VERSION,
        "folder": folder.resolve().name,
        "label": folder.as_posix() if not folder.is_absolute() else folder.name,
        "files": files,
        "checks": checks,
        "results": budget_results(folder),
    }


def sizing_page(data: dict) -> str:
    """
    The sizing editor's page, with the folder's files inside.

    Parameters
    ----------
    data : dict
        The folder's files, from `sizing_data`

    Returns
    -------
    page : str
        The page, as HTML text
    """
    return build_page("sizing", SCRIPTS, data, ("sizing",))


def write_sizing_editor(folder: str | Path, output: str | Path) -> Path:
    """
    Write the sizing editor's page for a folder of sizing files.

    Parameters
    ----------
    folder : str | Path
        The folder that holds the sizing files
    output : str | Path
        The folder to write the page in. It is made if it does not exist.

    Returns
    -------
    page : Path
        The page written. Double-click it to open the editor.
    """
    data = sizing_data(folder)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    page = output / PAGE_FILE
    page.write_text(sizing_page(data), encoding="utf-8")
    return page
