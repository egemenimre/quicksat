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

from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power.viewer import write_power_viewer
from quicksat.scenario import SCENARIO_FILE
from quicksat.thermal import THERMAL_FILE
from quicksat.thermal.folder import run_folder, summary


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
