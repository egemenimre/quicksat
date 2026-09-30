# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Basic satellite sizing tool.

"""

__version__ = "0.1.0"

from astropy import constants
from astropy import units as u
from astropy.units import Quantity

__all__ = ["MU_EARTH", "Q_", "R_EARTH", "u"]

Q_ = Quantity
"""Shorthand for astropy's `Quantity`, exported the way opticks exports it.

The package builds quantities with the constructor, `Q_(123, "m")`, and parses
text with `Q_("123 m")`; the notebooks write `123 * u.m` instead.
"""

# astropy.constants creates its constants at import, so pyright cannot see them
R_EARTH = constants.R_earth  # pyright: ignore[reportAttributeAccessIssue]
"""Earth equatorial radius: astropy's default, the IAU 2015 nominal 6378.1 km."""

MU_EARTH = constants.GM_earth  # pyright: ignore[reportAttributeAccessIssue]
"""Earth gravitational parameter: astropy's default, the IAU 2015 nominal GM.

A GM rather than G times astropy's `M_earth`. GM is the measured quantity, known
to about nine significant figures where G is known to about five, and astropy
derives `M_earth` from the two anyway.
"""
