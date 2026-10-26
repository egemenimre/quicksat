# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The Sizing Editor: a web page that fills in and edits a folder of sizing files, each
under its usual name.

It is built from the same shared parts as the Scenario Editor, as a page of its own,
since the sizing files share nothing with a scenario (`decisions.md` 9).
`docs/guides/sizing/edit_the_sizing_files.md` says how to use it.

"""

from pathlib import Path

from quicksat.editor.shared import (
    PAGE_FILE,
    build_page,
    csv_file,
    loader_check,
    yaml_file,
)

FORMAT = "quicksat-sizing-editor"
"""The `format` field of the data the page holds."""

VERSION = 1
"""The `version` field of the page's data, which stays the same in development."""

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
"""The Sizing Editor's own scripts in `templates/sizing/`, in the order they run after
the shared ones."""


def sizing_data(folder: str | Path) -> dict:
    """
    Everything the page needs from a folder of sizing files.

    Parameters
    ----------
    folder : str or Path
        The folder of sizing files, any of which may be missing

    Returns
    -------
    data : dict
        The format and version, the folder's name and label, with no local path, the
        files by kind, the loaders' checks, and the budgets' `results`

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
        kind: (csv_file(path) if path.suffix == ".csv" else yaml_file(path))
        if kind in found
        else None
        for kind, path in paths.items()
    }

    name = NAMES
    checks = []
    if "mission" in found:
        checks.append(
            loader_check(
                name["mission"], lambda: Mission.from_yaml_file(paths["mission"])
            )
        )
    if "requirements" in found:
        checks.append(
            loader_check(
                name["requirements"],
                lambda: Requirements.from_yaml_file(paths["requirements"]),
            )
        )
    if {"mass", "equipment"} <= found.keys():
        checks.append(
            loader_check(
                f"{name['equipment']} with {name['mass']}",
                lambda: MassBudget.from_csv(paths["equipment"], paths["mass"]),
            )
        )
    if "data" in found:
        checks.append(
            loader_check(
                name["data"], lambda: DataFlowModel.from_yaml_file(paths["data"])
            )
        )
    if {"deltav", "manoeuvres", "mission"} <= found.keys():
        checks.append(
            loader_check(
                f"{name['manoeuvres']} with {name['deltav']}",
                lambda: DeltaVBudget.from_csv(
                    paths["manoeuvres"], paths["deltav"], paths["mission"]
                ),
            )
        )
    if "agility" in found:
        checks.append(
            loader_check(
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
    The Sizing Editor's page, with the folder's files inside.

    Parameters
    ----------
    data : dict
        The folder's files, from `sizing_data`

    Returns
    -------
    page : str
        The page, as HTML
    """
    return build_page("sizing", SCRIPTS, data, ("sizing",))


def write_sizing_editor(folder: str | Path, output: str | Path) -> Path:
    """
    Write the Sizing Editor's page for a folder of sizing files.

    Parameters
    ----------
    folder : str or Path
        The folder of sizing files
    output : str or Path
        The folder for the page, made if missing

    Returns
    -------
    page : Path
        The page, which opens in a browser
    """
    data = sizing_data(folder)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    page = output / PAGE_FILE
    page.write_text(sizing_page(data), encoding="utf-8")
    return page
