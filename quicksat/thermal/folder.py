# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power budget and the payload's heat account of a folder, for the command and the
editor's server.

"""

from pathlib import Path

import pandas as pd

from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power import folder as power_folder
from quicksat.power.budget import BudgetRun
from quicksat.scenario import SCENARIO_FILE
from quicksat.thermal import THERMAL_FILE
from quicksat.thermal.account import ThermalRun, run_thermal
from quicksat.thermal.config import PayloadThermal

NO_THERMAL_FILE = "No {name} in the folder, so the power budget alone."
"""The note when the folder has no thermal file."""


def run_folder(
    folder: Path,
    scenario_file: str = SCENARIO_FILE,
    power_file: str = POWER_FILE,
    consumption_files: dict[str, str] = CONSUMPTION_FILES,
    thermal_file: str = THERMAL_FILE,
) -> tuple[BudgetRun, ThermalRun | None]:
    """
    The power budget of a folder, and the heat account when it has the thermal file,
    with every file read before the one run.

    Parameters
    ----------
    folder : Path
        The folder
    scenario_file, power_file : str, optional
        The files' names, if not the usual ones
    consumption_files : dict of str to str, optional
        The consumption files' names by group, if not the usual ones
    thermal_file : str, optional
        The optional thermal file's name, if not the usual one

    Returns
    -------
    budget : BudgetRun
        The power budget
    thermal : ThermalRun or None
        The heat account, or None without the thermal file
    """
    thermal_path = folder / thermal_file
    thermal = (
        PayloadThermal.from_yaml_file(thermal_path) if thermal_path.is_file() else None
    )
    budget = power_folder.run_folder(
        folder, scenario_file, power_file, consumption_files
    )
    if thermal is None:
        return budget, None
    account = run_thermal(
        thermal,
        budget.consumption.consumption["payload"],
        budget.power_system,
        budget.generation.run,
    )
    return budget, account


def _table(table: pd.DataFrame) -> str:
    """A table of the heat account as text, with one decimal."""
    if (table["ΔT note"] == "").all():
        table = table.drop(columns="ΔT note")
    return table.to_string(index=False, float_format=lambda value: f"{value:.1f}")


def summary(
    budget: BudgetRun, thermal: ThermalRun | None, thermal_file: str = THERMAL_FILE
) -> str:
    """
    The power command's text, then the heat account's tables and notes, or a note that
    there is no thermal file.

    Parameters
    ----------
    budget : BudgetRun
        The power budget
    thermal : ThermalRun or None
        The heat account
    thermal_file : str, optional
        The thermal file's name, for the note

    Returns
    -------
    text : str
        The results
    """
    lines = [power_folder.summary(budget), ""]
    if thermal is None:
        return "\n".join([*lines, NO_THERMAL_FILE.format(name=thermal_file)])
    lines += ["Payload heat account, by activity:"]
    lines += [_table(thermal.activity_table), "", "By payload mode:"]
    lines += [_table(thermal.mode_table), *thermal.notes]
    return "\n".join(lines)
