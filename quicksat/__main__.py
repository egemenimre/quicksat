# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Copy quicksat's sample into a folder, from the command line:

    python -m quicksat init my_satellite

The folder must be empty. `--from` takes a local copy of the repository. See
`quicksat.sample`.

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
    """Where everything went, and how to start, with the copy's own paths."""
    sizing, scenario, power = folder / "sizing", folder / "scenario", folder / "power"
    width = len(f"{scenario}/") + 2
    places = {
        sizing: "the sizing budgets: mass, data, delta-V and agility",
        scenario: "a timeline on an orbit: eclipses, attitudes and passes",
        power: "the same with the power budget",
    }
    where = "\n".join(f"  {f'{path}/':<{width}}{what}" for path, what in places.items())
    return f"""
Where everything is:
{where}
In each of the three:
  data/          the input files: the ones you edit
  editor/        the editor page, written for data/
  output/        the viewer, written by a run (scenario and power only)
  *.ipynb        the worked examples, for Jupyter

Your input files:
  {sizing / "data"}/
  {scenario / "data"}/
  {power / "data"}/

To edit and view the power sample with the editor's server:
  1. Start the server, and keep this terminal open:
       python -m quicksat.editor serve {power / "data"} {power / "output"}
  2. The Scenario Editor opens in your browser. If it does not, open the
     address that the server prints.
  3. Edit the files on the page. The Activities tab is the Activity
     Designer: Generate scenario runs the list, and shows it above the list.
  4. Click Create the viewer, on the Files tab or the last Setup step. It
     writes {power / "output" / "power_viewer.html"}.
  5. Click Open the viewer. After each Update the viewer, click it again, or
     reload the viewer's tab.
  6. To keep your changes, download them from the page and put them back in
     data/. On the Activities tab, Save into the folder writes the scenario
     file there itself. Nothing else on the page changes the files in data/.
  7. When you are done, click Stop the server at the top right of the page,
     or press Ctrl+C in the terminal.
For the scenario sample, give {scenario / "data"} and {scenario / "output"}.

The Sizing Editor needs no server. Double-click
  {sizing / "editor" / "editor.html"}"""


if __name__ == "__main__":
    main()
