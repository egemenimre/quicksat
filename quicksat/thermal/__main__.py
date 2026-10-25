# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Run the power budget and the payload's heat account in a folder, from the command
line:

    python -m quicksat.thermal sample/power/data sample/power/output

Thermal is a sub-domain of power, so this command does all that
`python -m quicksat.power` does: it runs the scenario and the power budget,
prints the budget's checks and writes the power viewer. With `payload_thermal.yaml`
in the folder, it also prints the payload's heat account, by activity and by
payload mode, after the checks. Without it, it says so, and gives the power
budget alone. The viewer does not show the heat account yet, so no file is
written for it.

A file that quicksat cannot read stops it with the error, and nothing is
written. A check that fails does not stop the command.

"""

import argparse
from pathlib import Path

import pandas as pd

from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power import __main__ as power_command
from quicksat.power.budget import BudgetRun
from quicksat.power.viewer import write_power_viewer
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
    The power budget of a folder, and the payload's heat account when the folder
    has the thermal file.

    The thermal file is read first, and then the power files, before the run, so
    that a mistake in any of them stops it at once. The heat account takes the
    power budget's run and files, so the scenario runs once.

    Parameters
    ----------
    folder : Path
        The folder
    scenario_file, power_file : str, optional
        The files' names, if not the usual ones
    consumption_files : dict of str to str, optional
        The consumption files' names by the group's name, `payload` and
        `platform`, if not the usual ones
    thermal_file : str, optional
        The thermal file's name, if not the usual one. The file is optional.

    Returns
    -------
    budget : BudgetRun
        The power budget
    thermal : ThermalRun or None
        The payload's heat account, or None without the thermal file
    """
    thermal_path = folder / thermal_file
    thermal = (
        PayloadThermal.from_yaml_file(thermal_path) if thermal_path.is_file() else None
    )
    budget = power_command.run_folder(
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
    The power budget's results as the power command prints them, then the heat
    account's.

    Parameters
    ----------
    budget : BudgetRun
        The power budget
    thermal : ThermalRun or None
        The payload's heat account, or None without the thermal file
    thermal_file : str, optional
        The thermal file's name, for the note when there is no account

    Returns
    -------
    text : str
        The power command's text. Then the heat account's tables by activity and
        by payload mode, the powers as means in W, and its notes. Without the
        account, a note that the folder has no thermal file.
    """
    lines = [power_command.summary(budget), ""]
    if thermal is None:
        return "\n".join([*lines, NO_THERMAL_FILE.format(name=thermal_file)])
    lines += ["Payload heat account, by activity:"]
    lines += [_table(thermal.activity_table), "", "By payload mode:"]
    lines += [_table(thermal.mode_table), *thermal.notes]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """
    Run the budget and the heat account, print their results, write the power
    viewer and print where it went.

    Parameters
    ----------
    argv : list of str, optional
        The arguments, the command line's by default
    """
    parser = argparse.ArgumentParser(
        prog="python -m quicksat.thermal",
        description="Run the power budget and the payload's heat account in a "
        "folder, and write the power viewer.",
    )
    parser.add_argument(
        "folder",
        help=f"the folder that holds {SCENARIO_FILE}, {POWER_FILE}, "
        f"{CONSUMPTION_FILES['payload']} and {CONSUMPTION_FILES['platform']}, "
        f"and {THERMAL_FILE} for the payload's heat account",
    )
    parser.add_argument("output", help="the folder to write the viewer in")
    args = parser.parse_args(argv)
    try:
        budget, thermal = run_folder(Path(args.folder))
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(summary(budget, thermal))
    print(write_power_viewer(budget, args.output))


if __name__ == "__main__":
    main()
