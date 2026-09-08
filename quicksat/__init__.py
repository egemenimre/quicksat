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
