# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
What the CCSDS messages that quicksat reads share: KVN lines and epochs.

KVN is the plain-text form of a CCSDS message: `KEY = value` lines, with
`COMMENT` lines and blank lines between them. A value may end with its unit in
brackets, such as `15.28 [rev/day]`. An epoch is a date, `2026-10-01T00:00:00`,
or a day of the year, `2026-274T00:00:00`, with an optional `Z`.

`quicksat.orbit.oem_trajectory` and `quicksat.orbit.omm` use these.

"""

import re
from pathlib import Path

_DAY_OF_YEAR = re.compile(r"^(\d{4})-(\d{3})T(.+)$")
"""An epoch given as a day of the year, such as 2026-274T00:00:00."""

_UNIT = re.compile(r"\s*\[[^\]]*\]$")
"""A unit in brackets at the end of a value, such as [rev/day]."""


def key_value(line: str, number: int, path: Path) -> tuple[str, str]:
    """
    The key and the value of a `KEY = value` line, without a unit in brackets.

    Parameters
    ----------
    line : str
        The line, without the spaces at its ends
    number : int
        Its line number, for the message
    path : Path
        The file, for the message

    Returns
    -------
    key, value : str
        The key in upper case, and the value without the spaces at its ends or
        a unit in brackets

    Raises
    ------
    ValueError
        If the line has no `=`, or nothing before it
    """
    key, equals, value = line.partition("=")
    if not equals or not key.strip():
        raise ValueError(f"{path}, line {number}: expected KEY = value, got '{line}'")
    return key.strip().upper(), _UNIT.sub("", value.strip())


def normalised_epoch(epoch: str) -> str:
    """
    A CCSDS epoch as astropy reads it: a date in ISO form, or a day of the year
    in astropy's `yday` form.

    Parameters
    ----------
    epoch : str
        The epoch as written, with an optional `Z`

    Returns
    -------
    epoch : str
    """
    epoch = epoch.strip().removesuffix("Z")
    match = _DAY_OF_YEAR.match(epoch)
    if match:
        year, day, clock = match.groups()
        return f"{year}:{day}:{clock}"
    return epoch
