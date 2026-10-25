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

Or serve the editor from this computer. The Scenario Editor gets a button that
runs the files and writes the viewer into the output folder. The Sizing Editor
works out the budgets as the files change, and needs no output folder:

    python -m quicksat.editor serve sample/power/data sample/power/output
    python -m quicksat.editor serve sample/sizing/data

See `quicksat.editor.server`.

"""

import argparse
import sys
from pathlib import Path

from quicksat.editor.scenario import write_editor
from quicksat.editor.sizing import NAMES, write_sizing_editor
from quicksat.scenario import SCENARIO_FILE


def main(argv: list[str] | None = None) -> None:
    """
    Write the editor page, and print where it went. Or, after `serve`, serve it.

    Parameters
    ----------
    argv : list of str, optional
        The arguments, the command line's by default
    """
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["serve"]:
        serve_main(argv[1:])
        return
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


def serve_main(argv: list[str]) -> None:
    """
    Serve the editor for a folder, until the user stops it.

    Parameters
    ----------
    argv : list of str
        The arguments after `serve`
    """
    parser = argparse.ArgumentParser(
        prog="python -m quicksat.editor serve",
        description="Serve the editor for a folder, on this computer only. The "
        "Scenario Editor's Create the viewer button runs the page's files, and "
        "writes the viewer into the output folder. The Sizing Editor's Budgets tab "
        "works out the budgets as the files change.",
    )
    parser.add_argument(
        "folder",
        help=f"the folder that holds {SCENARIO_FILE}, or the sizing files",
    )
    parser.add_argument(
        "output",
        nargs="?",
        help="the folder to write the viewer in, for the Scenario Editor",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="the port to listen on, and 0 for any free one: 8780 by default, or "
        "the next free one",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the editor in the browser",
    )
    args = parser.parse_args(argv)
    # here, so that writing a page does not import the run
    from quicksat.editor.server import EditorServer, serve

    try:
        server = EditorServer(args.folder, args.output, args.port)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    serve(server, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
