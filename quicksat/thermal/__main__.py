# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Run the power budget and the payload's heat account in a folder, from the command line:

    python -m quicksat.thermal sample/power/data sample/power/output

It does all that `python -m quicksat.power` does, then prints the heat account by
activity and by payload mode, or says the folder has no thermal file. The viewer then
has a Thermal tab with the account.

"""

import argparse
from pathlib import Path

from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power.viewer import write_power_viewer
from quicksat.scenario import SCENARIO_FILE
from quicksat.thermal import THERMAL_FILE
from quicksat.thermal.folder import run_folder, summary
from quicksat.thermal.viewer import thermal_data


def main(argv: list[str] | None = None) -> None:
    """
    Run the budget and the heat account, print their results, and write the power
    viewer.

    Parameters
    ----------
    argv : list of str, optional
        The arguments, by default the command line's
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
    account = None if thermal is None else thermal_data(thermal)
    print(write_power_viewer(budget, args.output, account))


if __name__ == "__main__":
    main()
