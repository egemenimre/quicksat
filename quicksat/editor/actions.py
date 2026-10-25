# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The work that the editor's server does for a page's requests.

Each request sends the page's files. `run_files` runs them and writes the
viewer, `design_files` runs the scenario for the Activity Designer,
`thermal_files` works out the payload's heat account, and `budget_files` works
out the sizing budgets. Each writes the files into a temporary folder first, and
reads them there with quicksat's loaders. `save_files` writes the changed files
into the input folder.

`quicksat.editor.server` answers the requests, and calls these.

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
from quicksat.editor.thermal import surfaces_key, thermal_results
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
"""The files that the Activity Designer reads, with their loaders. It runs the
scenario alone, so it leaves the power files out."""


def _relative(name: str) -> str | None:
    """
    A file's name as a relative path in `/` form, or None if it is absolute.

    Parameters
    ----------
    name : str
        The name as the scenario gives it, with `/` or `\\`

    Returns
    -------
    path : str or None
        The name, normalised, such as `../models/sat.glb`
    """
    name = name.replace("\\", "/")
    if name.startswith("/") or PureWindowsPath(name).drive:
        return None
    return posixpath.normpath(name)


def _write_inputs(root: Path, files: list[dict]) -> tuple[Path, dict]:
    """
    Write the page's files into a folder, where the scenario will find them.

    The scenario names its 3D model, its orbit file and its satellite targets'
    files by a path from its own folder, which may start with `..`. So the scenario goes deep enough inside `root` for
    each such path to stay inside it too. A file named by an absolute path is not
    written: quicksat reads it from where it is.

    Parameters
    ----------
    root : Path
        An empty folder
    files : list of dict
        The page's files, each with `kind`, `name`, and `text` or `base64`

    Returns
    -------
    base : Path
        The folder that holds the scenario file
    names : dict
        The names of the files that quicksat reads, by kind

    Raises
    ------
    ValueError
        If a file has no name, or the scenario, the power system or the
        consumption is not a plain file name
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
    Write the page's files into a temporary folder, check them, and run them.

    The folder is deleted after the run. quicksat's loaders read each file that
    `roles` names. If they all read, `work` runs on the folder.

    Parameters
    ----------
    files : list of dict
        The page's files, as `_write_inputs` takes them
    roles : dict
        The loader of each kind of file to check, by the kind
    work : callable
        Runs the files, given the folder of the scenario and the names of the
        files by kind. It gives the result's own fields.

    Returns
    -------
    result : dict
        `ok`, and `checks`, what the loaders said of each file. When `ok`, the
        fields from `work`, and `seconds`, the time taken. Otherwise `error`,
        the reason, with no temporary path in it.
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
    Run the editor's files, and write the viewer.

    The files go in a temporary folder, which is deleted after the run. quicksat's
    loaders read the scenario and, if there are any, the power system and the
    two consumption files. If they all read, the run goes ahead: the power
    budget when the power system and both consumption files are there, and the
    scenario alone otherwise. The viewer
    goes in `output`, as `python -m quicksat.scenario` or `python -m quicksat.thermal`
    would write it. With the thermal file too, the report gives the payload's heat
    account.

    Parameters
    ----------
    files : list of dict
        The page's files, each with `kind`: `scenario`, `model`, `orbit`,
        `power`, `payload_consumption`, `platform_consumption`, or `target:`
        and the file's name for a
        satellite target's file. `name`: the name the scenario gives it, or the
        file's own name. `text`, or `base64` for the 3D model.
    output : str | Path
        The folder to write the viewer in. It is made if it does not exist.

    Returns
    -------
    result : dict
        `ok`, and `checks`, what quicksat's loaders said of each file, as the
        editor's page holds them. When `ok`: `page`, the viewer's page in
        `output`, `report`, the results as the command prints them, and
        `seconds`, the time taken. Otherwise `error`, the reason, with no
        temporary path in it.
    """

    def work(base: Path, names: dict) -> dict:
        consumption = {group: names.get(f"{group}_consumption") for group in GROUPS}
        if "power" in names and all(consumption.values()):
            thermal_file = names.get("payload_thermal", THERMAL_FILE)
            budget, thermal = run_folder(
                base, names["scenario"], names["power"], consumption, thermal_file
            )
            return {
                "page": write_power_viewer(budget, output).name,
                "report": summary(budget, thermal, thermal_file),
            }
        run = run_scenario(Scenario.from_yaml_file(base / names["scenario"]))
        return {"page": write_scenario_viewer(run, output).name, "report": run.report}

    return _run_inputs(files, _ROLES, work)


def design_files(files: list[dict], repeat: bool) -> dict:
    """
    Run the editor's scenario for the Activity Designer, and write nothing.

    The files go in a temporary folder, as for `run_files`. The scenario is read
    as the designer reads it, so its list of activities may be empty. The power
    files are left out, and the scenario runs alone.

    Parameters
    ----------
    files : list of dict
        The page's files, as `run_files` takes them
    repeat : bool
        Whether to repeat the list of activities until the run ends, or run it
        once

    Returns
    -------
    result : dict
        `ok`, `checks` and `seconds`, or `error`, as from `run_files`. When `ok`:
        `data`, the viewer's data from `scenario_data` for the designer, and
        `id`, its id. `rows`, the results of each activity from
        `activity_rows`, and `warnings`, the run's warnings. `duration_s`, the
        run's length, `period_s`, the orbit's period, and `pass_s`, the length
        of one pass of the list, or None. `max_rate_deg_s` and
        `max_acceleration_deg_s2`, the slew block's limits, or None.
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
    Work out the payload's heat account from the editor's files, and write
    nothing.

    The files go in a temporary folder, as for `run_files`. The run and the
    surfaces' heat are kept in `cache` with `surfaces_key`. A request with the
    same key reuses them, so a change to the heaters, the flows or the
    dissipation only redoes the sums.

    Parameters
    ----------
    files : list of dict
        The page's files, as `run_files` takes them. They must hold the power
        system file, the payload's consumption file and the thermal file.
    cache : dict
        The server's cache, which this reads and fills: `key`, `run` and
        `surfaces`

    Returns
    -------
    result : dict
        `ok`, `checks` and `seconds`, or `error`, as from `run_files`. When
        `ok`: `results`, from `thermal_results`, and `reused`, whether the run
        and the surfaces' heat came from the cache.
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
        return {"results": thermal_results(account), "reused": reused}

    return _run_inputs(files, _ROLES, work)


def budget_files(files: list[dict]) -> dict:
    """
    Work out the sizing budgets from the Sizing Editor's files, and write nothing.

    The files go in a temporary folder, under their kinds' usual names, which is
    deleted afterwards. A file of a kind that the sizing folder does not have is
    left out.

    Parameters
    ----------
    files : list of dict
        The page's files, each with `kind`, such as `mission` or `equipment`, and
        `text`

    Returns
    -------
    result : dict
        `ok`, `results`, from `budget_results`, with no temporary path in them,
        and `seconds`, the time taken. Otherwise `error`, the reason.
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
    Write the page's files into the input folder, unless one changed on disk.

    Each file names the SHA-256 of the file as the page last read or saved it. A
    file whose bytes on disk no longer match was changed since, by another
    program or another page, so none of the files is written. Each file goes
    in a temporary file in the same folder first, which then takes its place.
    So a failure leaves the old file whole.

    Parameters
    ----------
    folder : str | Path
        The input folder
    files : list of dict
        Each with `name`, its path from the folder, `text`, and `sha256`, the
        hash of the file as the page last read or saved it, or None for a file
        the folder did not have

    Returns
    -------
    result : dict
        `ok`, and `files`, each file's `name` and the `sha256` of its new
        bytes, for the page's next save. Otherwise `error`, the reason, and
        nothing is written.
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
