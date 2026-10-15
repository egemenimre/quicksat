# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Write the editor page for a folder of input files, from the command line:

    python -m quicksat.editor sample/power/data sample/power/editor
    python -m quicksat.editor sample/sizing/data sample/sizing/editor

A folder with a `scenario.yaml` gets the Scenario Editor, and a folder of sizing
files, such as `mission.yaml`, gets the Sizing Editor.

"""

import argparse
from pathlib import Path

from quicksat.editor.editor import write_editor
from quicksat.editor.sizing import NAMES, write_sizing_editor
from quicksat.scenario import SCENARIO_FILE


def main(argv: list[str] | None = None) -> None:
    """
    Write the editor page, and print where it went.

    Parameters
    ----------
    argv : list of str, optional
        The arguments, the command line's by default
    """
    parser = argparse.ArgumentParser(
        prog="python -m quicksat.editor",
        description="Write the editor page for a folder of input files: the "
        "Scenario Editor for a folder with a scenario.yaml, and the Sizing Editor "
        "for a folder of sizing files.",
    )
    parser.add_argument("folder", help="the folder that holds the input files")
    parser.add_argument("output", help="the folder to write the page in")
    args = parser.parse_args(argv)
    folder = Path(args.folder)
    if (folder / SCENARIO_FILE).is_file():
        print(write_editor(folder, args.output))
    elif any((folder / name).is_file() for name in NAMES.values()):
        print(write_sizing_editor(folder, args.output))
    else:
        parser.error(
            f"{args.folder} holds no {SCENARIO_FILE} and no sizing file, "
            "such as mission.yaml"
        )


if __name__ == "__main__":
    main()
