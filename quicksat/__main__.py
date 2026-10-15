# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Copy quicksat's sample into a folder, from the command line:

    python -m quicksat init my_satellite

The sample comes from GitHub, for the installed version, with its data, its
notebooks, and the viewers and editor pages written from them. `--from` takes a
local copy of the repository instead, as a folder or as its zip. The folder must
be empty, so nothing is overwritten. See `quicksat.sample`.

"""

import argparse
from pathlib import Path

from quicksat.sample import copy_sample


def main(argv: list[str] | None = None) -> None:
    """
    Copy the sample, and print what to do next.

    Parameters
    ----------
    argv : list of str, optional
        The arguments, the command line's by default
    """
    parser = argparse.ArgumentParser(
        prog="python -m quicksat",
        description="Copy quicksat's sample into a folder.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init",
        help="copy the sample into a folder",
        description="Copy quicksat's sample, from GitHub, into an empty folder.",
    )
    init.add_argument("folder", help="the folder to copy into, made if missing")
    init.add_argument(
        "--from",
        dest="source",
        metavar="PATH",
        help="a local copy of the repository, as a folder or as its zip",
    )
    args = parser.parse_args(argv)
    try:
        files, warnings = copy_sample(args.folder, args.source)
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    for warning in warnings:
        print(f"warning: {warning}")
    print(f"Copied {len(files)} files into {args.folder}.")
    print(_next_steps(Path(args.folder)))


def _next_steps(folder: Path) -> str:
    """What to do with the copied sample, with its own paths."""
    power = folder / "power"
    sizing = folder / "sizing"
    return f"""
Next:
  Open the power sample in the Scenario Editor, served from this computer:
    python -m quicksat.editor serve {power / "data"} {power / "output"}
  Or double-click a page written already, such as
    {power / "output" / "power_viewer.html"}
    {sizing / "editor" / "editor.html"}
  The notebooks in {sizing}, {folder / "scenario"} and {power} are the worked
  examples, for Jupyter."""


if __name__ == "__main__":
    main()
