# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
What the CCSDS messages that quicksat reads share: KVN lines and epochs.

KVN is the text form: `KEY = value` lines, with `COMMENT` and blank lines, and an
optional unit in brackets. An epoch is a date or a day of the year, with an optional
`Z`.

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
        The line, stripped
    number : int
        Its line number, for the message
    path : Path
        The file, for the message

    Returns
    -------
    key, value : str
        The key in upper case, and the value stripped

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
    A CCSDS epoch as astropy reads it: an ISO date, or astropy's `yday` form.

    Parameters
    ----------
    epoch : str
        The epoch as written

    Returns
    -------
    epoch : str
        The epoch without its `Z`
    """
    epoch = epoch.strip().removesuffix("Z")
    match = _DAY_OF_YEAR.match(epoch)
    if match:
        year, day, clock = match.groups()
        return f"{year}:{day}:{clock}"
    return epoch
