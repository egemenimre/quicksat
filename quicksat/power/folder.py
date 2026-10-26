# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power budget of a folder of input files.

`run_folder` reads the folder's four files and runs the budget, and `summary`
gives the results as text. `python -m quicksat.power` prints them, and the
thermal command and the editor's server build on them.

"""

from pathlib import Path

from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power.budget import BudgetRun, run_budget
from quicksat.power.config import PowerSystem
from quicksat.power.consumption import PowerConsumption, run_consumption
from quicksat.power.generation import run_generation
from quicksat.scenario import SCENARIO_FILE
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario


def run_folder(
    folder: Path,
    scenario_file: str = SCENARIO_FILE,
    power_file: str = POWER_FILE,
    consumption_files: dict[str, str] = CONSUMPTION_FILES,
) -> BudgetRun:
    """
    The power budget of a folder's four files.

    All four are read before the run, so that a mistake in any of them stops it
    at once.

    Parameters
    ----------
    folder : Path
        The folder
    scenario_file, power_file : str, optional
        The files' names, if not the usual ones
    consumption_files : dict of str to str, optional
        The consumption files' names by the group's name, `payload` and
        `platform`, if not the usual ones

    Returns
    -------
    budget : BudgetRun
        The budget
    """
    scenario = Scenario.from_yaml_file(folder / scenario_file)
    power_system = PowerSystem.from_yaml_file(folder / power_file)
    consumption = {
        group: PowerConsumption.from_csv(folder / name)
        for group, name in consumption_files.items()
    }
    run = run_scenario(scenario)
    generation = run_generation(power_system, run)
    return run_budget(power_system, generation, run_consumption(consumption, run))


def summary(budget: BudgetRun) -> str:
    """
    The budget's results as the command prints them.

    Parameters
    ----------
    budget : BudgetRun
        The budget

    Returns
    -------
    text : str
        The scenario's report, the notes on the generation and the loads, and
        the three checks, one a line
    """
    lines = [budget.generation.run.report]
    lines += budget.generation.notes + budget.consumption.notes
    lines += [
        f"{check.status:<4} {check.name}: {check.detail}" for check in budget.checks
    ]
    return "\n".join(lines)
