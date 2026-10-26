# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Run the power budget in a folder and write its viewer, from the command line:

    python -m quicksat.power sample/power/data sample/power/output

The folder holds `scenario.yaml`, `power_system.yaml`, and the two consumption
files `payload_consumption.csv` and `platform_consumption.csv`, with the 3D
model and any orbit file they name, as for the editor. The command prints the scenario's results, the notes on the
generation and the loads, and the budget's three checks. Then it writes the
viewer and prints where the page went. A file that quicksat cannot read stops it
with the error, and nothing is written.

A check that fails does not stop the command: the viewer shows the failing run
too.

"""

import argparse
from pathlib import Path

from quicksat.power import CONSUMPTION_FILES, POWER_FILE
from quicksat.power.folder import run_folder, summary
from quicksat.power.viewer import write_power_viewer
from quicksat.scenario import SCENARIO_FILE


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
        help=f"the folder that holds {SCENARIO_FILE}, {POWER_FILE}, "
        f"{CONSUMPTION_FILES['payload']} and {CONSUMPTION_FILES['platform']}",
    )
    parser.add_argument("output", help="the folder to write the viewer in")
    args = parser.parse_args(argv)
    try:
        budget = run_folder(Path(args.folder))
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(summary(budget))
    print(write_power_viewer(budget, args.output))


if __name__ == "__main__":
    main()
