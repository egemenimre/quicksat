# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Basic satellite sizing tool.

"""

__version__ = "0.1.0"

import pint

u = pint.UnitRegistry()
"""The shared unit registry.

Every `Quantity` in quicksat must originate from this registry — pint refuses to
combine quantities built by different registries.
"""

# make this the registry pint falls back on (e.g. when unpickling)
pint.set_application_registry(u)

Q_ = u.Quantity
"""Shorthand for the registry-bound Quantity class."""

# pint carries standard_gravity, which the rocket equation needs, but no Earth
# constants. `earth_mu` is the measured GM rather than gravitational_constant x
# earth_mass: GM is known to about nine significant figures where G is known to
# five, so deriving it would throw four of them away.
u.define("earth_radius = 6378.137 km = R_earth")  # WGS-84 equatorial
u.define("earth_mu = 398600.4418 km**3 / s**2 = GM_earth")  # EGM96

R_EARTH = Q_(1, "earth_radius")
"""Earth equatorial radius, WGS-84."""

MU_EARTH = Q_(1, "earth_mu")
"""Earth gravitational parameter, EGM96."""
