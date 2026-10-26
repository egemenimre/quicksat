# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Run the scenario in a folder and write its viewer, from the command line:

    python -m quicksat.scenario sample/scenario/data sample/scenario/output

It prints the run's summary, the occurrences with a problem and the warnings. A file
that quicksat cannot read stops it, and nothing is written.

"""

import argparse
from pathlib import Path

from quicksat.scenario import SCENARIO_FILE
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.scenario.viewer import write_scenario_viewer


def main(argv: list[str] | None = None) -> None:
    """
    Run the scenario, print its results, and write the viewer.

    Parameters
    ----------
    argv : list of str, optional
        The arguments, by default the command line's
    """
    parser = argparse.ArgumentParser(
        prog="python -m quicksat.scenario",
        description="Run the scenario in a folder, and write its viewer.",
    )
    parser.add_argument("folder", help=f"the folder that holds {SCENARIO_FILE}")
    parser.add_argument("output", help="the folder to write the viewer in")
    args = parser.parse_args(argv)
    try:
        run = run_scenario(Scenario.from_yaml_file(Path(args.folder) / SCENARIO_FILE))
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(run.report)
    print(write_scenario_viewer(run, args.output))


if __name__ == "__main__":
    main()
