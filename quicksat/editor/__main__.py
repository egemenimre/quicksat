# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Write the editor page for a folder of input files, from the command line:

    python -m quicksat.editor sample/power/data sample/power/editor

"""

import argparse

from quicksat.editor.editor import write_editor


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
        description="Write the editor page for a folder of input files.",
    )
    parser.add_argument("folder", help="the folder that holds the input files")
    parser.add_argument("output", help="the folder to write the page in")
    args = parser.parse_args(argv)
    print(write_editor(args.folder, args.output))


if __name__ == "__main__":
    main()
