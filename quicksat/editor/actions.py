# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The work that the editor's server does for a page's requests, which
`quicksat.editor.server` answers.

Each request's files go into a temporary folder, and quicksat's loaders read them there.
`save_files` writes the changed files into the input folder.

"""

import base64
import binascii
import hashlib
import json
import os
import posixpath
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from quicksat.editor.budgets import budget_results
from quicksat.editor.shared import loader_check
from quicksat.editor.sizing import NAMES as SIZING_NAMES
from quicksat.editor.thermal import surfaces_key
from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power.config import PowerSystem
from quicksat.power.consumption import PowerConsumption
from quicksat.power.viewer import write_power_viewer
from quicksat.scenario.config import Scenario
from quicksat.scenario.names import GROUPS
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import (
    activity_rows,
    scenario_data,
    write_scenario_viewer,
)
from quicksat.thermal import THERMAL_FILE
from quicksat.thermal.account import run_thermal
from quicksat.thermal.config import PayloadThermal
from quicksat.thermal.folder import run_folder, summary
from quicksat.thermal.surfaces import surface_powers
from quicksat.thermal.viewer import thermal_data

_ROLES = {
    "scenario": Scenario.from_yaml_file,
    "power": PowerSystem.from_yaml_file,
    "payload_consumption": PowerConsumption.from_csv,
    "platform_consumption": PowerConsumption.from_csv,
    "payload_thermal": PayloadThermal.from_yaml_file,
}
"""The files that quicksat reads, by their kind, with their loaders."""

_DESIGN_ROLES = {
    "scenario": lambda path: Scenario.from_yaml_file(path, designer=True),
}
"""The files that the Activity Designer reads, with their loaders: the scenario's
alone."""


def _relative(name: str) -> str | None:
    """
    A file's name as a relative path in `/` form, such as `../models/sat.glb`, or None
    if absolute.
    """
    name = name.replace("\\", "/")
    if name.startswith("/") or PureWindowsPath(name).drive:
        return None
    return posixpath.normpath(name)


def _write_inputs(root: Path, files: list[dict]) -> tuple[Path, dict]:
    """
    Write the page's files into a folder, with the scenario deep enough for each `..`
    path to stay inside, and give its folder and the names by kind.
    """
    paths = {}
    for file in files:
        name = file.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"The page sent a {file.get('kind', '')} file with no name."
            )
        paths[id(file)] = _relative(name)
    # a normalised path has its `..` at the start only
    depth = max((p.split("/").count("..") for p in paths.values() if p), default=0)
    base = root.joinpath(*[f"up{i}" for i in range(depth)], "folder")
    base.mkdir(parents=True)
    names = {}
    for file in files:
        path = paths[id(file)]
        if file.get("kind") in _ROLES:
            if path is None or "/" in path or path in (".", ".."):
                raise ValueError(
                    f"Cannot run a file named {file['name']}: give it a plain file name."
                )
            names[file["kind"]] = path
        if path is None:
            continue
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if "base64" in file:
            target.write_bytes(base64.b64decode(file["base64"], validate=True))
        else:
            target.write_text(str(file.get("text", "")), encoding="utf-8")
    return base, names


def _run_inputs(
    files: list[dict], roles: dict, work: Callable[[Path, dict], dict]
) -> dict:
    """
    Write the page's files into a temporary folder, check them with their loaders, and
    run `work` on them if they all read.
    """
    start = time.perf_counter()
    if not any(file.get("kind") == "scenario" for file in files):
        return {"ok": False, "error": "The page holds no scenario file.", "checks": []}
    with tempfile.TemporaryDirectory(prefix="quicksat_run_") as tmp:
        root = Path(tmp)

        def clean(text: str) -> str:
            return (
                text.replace(f"{base}/", "")
                .replace(str(base), "the folder")
                .replace(str(root), "")
            )

        try:
            base, names = _write_inputs(root, files)
        except (ValueError, binascii.Error) as error:
            return {"ok": False, "error": str(error), "checks": []}
        checks = []
        for kind, loader in roles.items():
            if kind in names:
                path = base / names[kind]
                check = loader_check(
                    names[kind], lambda read=loader, path=path: read(path)
                )
                checks.append({**check, "message": clean(check["message"])})
        refused = [check for check in checks if not check["ok"]]
        if refused:
            listed = ", ".join(check["file"] for check in refused)
            return {
                "ok": False,
                "error": f"quicksat cannot read {listed}, so it did not run the files.",
                "checks": checks,
            }
        try:
            result = work(base, names)
        except (OSError, ValueError) as error:
            return {"ok": False, "error": clean(str(error)), "checks": checks}
    return {
        "ok": True,
        **result,
        "checks": checks,
        "seconds": round(time.perf_counter() - start, 1),
    }


def run_files(files: list[dict], output: str | Path) -> dict:
    """
    Run the editor's files, and write the viewer, as the scenario, power or thermal
    command would.

    Parameters
    ----------
    files : list of dict
        The page's files, each with its `kind`, its `name`, and its `text` or `base64`
    output : str or Path
        The folder for the viewer, made if missing

    Returns
    -------
    result : dict
        `ok` and `checks`, then `page`, `report` and `seconds`, or `error`, with no
        temporary path in it
    """

    def work(base: Path, names: dict) -> dict:
        consumption = {group: names.get(f"{group}_consumption") for group in GROUPS}
        if "power" in names and all(consumption.values()):
            thermal_file = names.get("payload_thermal", THERMAL_FILE)
            budget, thermal = run_folder(
                base, names["scenario"], names["power"], consumption, thermal_file
            )
            account = None if thermal is None else thermal_data(thermal)
            return {
                "page": write_power_viewer(budget, output, account).name,
                "report": summary(budget, thermal, thermal_file),
            }
        run = run_scenario(Scenario.from_yaml_file(base / names["scenario"]))
        return {"page": write_scenario_viewer(run, output).name, "report": run.report}

    return _run_inputs(files, _ROLES, work)


def design_files(files: list[dict], repeat: bool) -> dict:
    """
    Run the editor's scenario alone for the Activity Designer, and write nothing.

    Parameters
    ----------
    files : list of dict
        The page's files, as `run_files` takes them
    repeat : bool
        Whether to repeat the list until the run ends

    Returns
    -------
    result : dict
        As from `run_files`, with the designer's `data`, its `id`, the activities'
        `rows`, the warnings, and the lengths and limits the page shows
    """
    files = [
        file
        for file in files
        if file.get("kind") not in _ROLES or file.get("kind") == "scenario"
    ]

    def work(base: Path, names: dict) -> dict:
        path = base / names["scenario"]
        run = run_scenario(Scenario.from_yaml_file(path, designer=True), repeat)
        data = scenario_data(run, designer=True)
        attitude = data["attitude"]
        return {
            "data": data,
            "id": data["id"],
            "rows": activity_rows(run),
            "warnings": data["warnings"],
            "duration_s": data["grid"]["t_s"][-1],
            "period_s": data["orbit"]["period_s"],
            "pass_s": data["designer"]["pass_s"],
            "max_rate_deg_s": attitude["max_rate_deg_s"],
            "max_acceleration_deg_s2": attitude["max_acceleration_deg_s2"],
        }

    return _run_inputs(files, _DESIGN_ROLES, work)


def thermal_files(files: list[dict], cache: dict) -> dict:
    """
    Work out the payload's heat account from the editor's files, and write nothing.

    The run and the surfaces' heat are kept in `cache` under `surfaces_key`, so a change
    to the heaters, the flows or the dissipation only redoes the sums.

    Parameters
    ----------
    files : list of dict
        The page's files, with the power system, the payload's consumption and the
        thermal file
    cache : dict
        The server's cache, read and filled: `key`, `run` and `surfaces`

    Returns
    -------
    result : dict
        As from `run_files`, with `results` from `thermal_data`, and whether the
        cache was `reused`
    """

    def work(base: Path, names: dict) -> dict:
        needed = {
            "power": POWER_FILE,
            "payload_consumption": CONSUMPTION_FILES["payload"],
            "payload_thermal": THERMAL_FILE,
        }
        missing = [name for kind, name in needed.items() if kind not in names]
        if missing:
            raise ValueError(f"The heat account needs {', '.join(missing)} too.")
        power_system = PowerSystem.from_yaml_file(base / names["power"])
        consumption = PowerConsumption.from_csv(base / names["payload_consumption"])
        thermal = PayloadThermal.from_yaml_file(base / names["payload_thermal"])
        key = surfaces_key(files, power_system, thermal)
        reused = cache.get("key") == key
        if reused:
            run, surfaces = cache["run"], cache["surfaces"]
        else:
            run = run_scenario(Scenario.from_yaml_file(base / names["scenario"]))
            surfaces = surface_powers(thermal, power_system, run)
            cache.clear()
            cache.update(key=key, run=run, surfaces=surfaces)
        account = run_thermal(thermal, consumption, power_system, run, surfaces)
        return {"results": thermal_data(account), "reused": reused}

    return _run_inputs(files, _ROLES, work)


def budget_files(files: list[dict]) -> dict:
    """
    Work out the sizing budgets from the Sizing Editor's files, and write nothing.

    Parameters
    ----------
    files : list of dict
        The page's files, each with its `kind` and `text`

    Returns
    -------
    result : dict
        `ok`, `results` from `budget_results`, and `seconds`, or `error`
    """
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="quicksat_budgets_") as tmp:
        root = Path(tmp)
        for file in files:
            name = SIZING_NAMES.get(str(file.get("kind")))
            text = file.get("text")
            if name is None:
                continue
            if not isinstance(text, str):
                return {"ok": False, "error": f"The page sent {name} with no text."}
            (root / name).write_text(text, encoding="utf-8")
        results = budget_results(root)
    # the messages may name the temporary folder
    text = json.dumps(results).replace(f"{root}{os.sep}", "").replace(str(root), "")
    return {
        "ok": True,
        "results": json.loads(text),
        "seconds": round(time.perf_counter() - start, 2),
    }


def file_hash(path: Path) -> str:
    """
    The SHA-256 of a file's bytes, as the page and the server compare it.

    Parameters
    ----------
    path : Path
        The file

    Returns
    -------
    sha256 : str
        64 hex digits
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_files(folder: str | Path, files: list[dict]) -> dict:
    """
    Write the page's files into the input folder, unless one changed on disk since the
    page read it.

    Each file goes into a temporary file first, which then takes its place, so a failure
    leaves the old one whole.

    Parameters
    ----------
    folder : str or Path
        The input folder
    files : list of dict
        Each with its `name` from the folder, its `text`, and the `sha256` the page last
        knew, or None for a new file

    Returns
    -------
    result : dict
        `ok`, and each file's `name` and new `sha256`, or `error`, with nothing written
    """
    folder = Path(folder).resolve()
    targets = []
    for file in files:
        name, text = file.get("name"), file.get("text")
        if not isinstance(name, str) or not isinstance(text, str):
            return {"ok": False, "error": "The page sent a file with no name or text."}
        target = (folder / name).resolve()
        if _relative(name) is None or not target.is_relative_to(folder):
            return {
                "ok": False,
                "error": f"Cannot save {name}: it is outside the folder.",
            }
        if target.is_dir():
            return {"ok": False, "error": f"Cannot save {name}: it is a folder."}
        loaded = file.get("sha256")
        now = file_hash(target) if target.is_file() else None
        if now != loaded:
            return {
                "ok": False,
                "error": f"{name} changed on disk since this page last read or "
                "saved it, so nothing was saved. Reload the page to see the file as "
                "it is now, or save your work as a download.",
            }
        targets.append((target, text.encode("utf-8")))
    saved = []
    for target, body in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".quicksat_")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(body)
            if target.is_file():
                shutil.copymode(target, temporary)
            os.replace(temporary, target)
        except OSError:
            Path(temporary).unlink(missing_ok=True)
            raise
        saved.append(
            {
                "name": target.relative_to(folder).as_posix(),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return {"ok": True, "files": saved}
