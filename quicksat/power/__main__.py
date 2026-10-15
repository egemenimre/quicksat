# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Run the power budget in a folder and write its viewer, from the command line:

    python -m quicksat.power sample/power/data sample/power/output

The folder holds `scenario.yaml`, `power_system.yaml` and
`power_consumption.csv`, with the 3D model and any orbit file they name, as for
the editor. The command prints the scenario's results, the notes on the
generation and the loads, and the budget's three checks. Then it writes the
viewer and prints where the page went. A file that quicksat cannot read stops it
with the error, and nothing is written.

A check that fails does not stop the command: the viewer shows the failing run
too.

"""

import argparse
from pathlib import Path

from quicksat.editor.editor import CONSUMPTION_FILE, POWER_FILE, SCENARIO_FILE
from quicksat.power.budget import BudgetRun, run_budget
from quicksat.power.config import PowerSystem
from quicksat.power.consumption import PowerConsumption, run_consumption
from quicksat.power.generation import run_generation
from quicksat.power.viewer import write_power_viewer
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario


def run_folder(folder: Path) -> BudgetRun:
    """
    The power budget of a folder's three files.

    All three are read before the run, so that a mistake in any of them stops it
    at once.

    Parameters
    ----------
    folder : Path
        The folder

    Returns
    -------
    budget : BudgetRun
        The budget
    """
    scenario = Scenario.from_yaml_file(folder / SCENARIO_FILE)
    power_system = PowerSystem.from_yaml_file(folder / POWER_FILE)
    consumption = PowerConsumption.from_csv(folder / CONSUMPTION_FILE)
    run = run_scenario(scenario)
    generation = run_generation(power_system, run)
    return run_budget(power_system, generation, run_consumption(consumption, run))


def main(argv: list[str] | None = None) -> None:
    """
    Run the budget, print its results, write the viewer and print where it went.

    Parameters
    ----------
    argv : list of str, optional
        The arguments, the command line's by default
    """
    parser = argparse.ArgumentParser(
        prog="python -m quicksat.power",
        description="Run the power budget in a folder, and write its viewer.",
    )
    parser.add_argument(
        "folder",
        help=f"the folder that holds {SCENARIO_FILE}, {POWER_FILE} and "
        f"{CONSUMPTION_FILE}",
    )
    parser.add_argument("output", help="the folder to write the viewer in")
    args = parser.parse_args(argv)
    try:
        budget = run_folder(Path(args.folder))
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(budget.generation.run.report)
    for note in budget.generation.notes + budget.consumption.notes:
        print(note)
    for check in budget.checks:
        print(f"{check.status:<4} {check.name}: {check.detail}")
    print(write_power_viewer(budget, args.output))


if __name__ == "__main__":
    main()
