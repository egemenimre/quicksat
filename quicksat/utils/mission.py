# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The mission, and the quantities every budget derives from it.

Each fact is stated once, so the budgets cannot disagree. The orbit is circular, with no
perturbations or drag. `docs/sizing/mission_ref.ipynb` explains it.

"""

import numpy as np
from pydantic import ConfigDict

from quicksat import MU_EARTH, Q_, R_EARTH, u
from quicksat.utils.parser_helpers import AngleQty, LengthQty, TimeQty, YamlFile


class Mission(YamlFile):
    """
    A mission: a circular Earth orbit, and how long it is flown.

    Parameters
    ----------
    altitude : Quantity
        Height above the Earth's equatorial radius
    inclination : Quantity
        The orbit's inclination, for the plane changes
    duration : Quantity
        The design life, which scales the recurring manoeuvres
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    altitude: LengthQty
    inclination: AngleQty
    duration: TimeQty

    @property
    def radius(self):
        """The orbit's radius from the Earth's centre, in km."""
        return (R_EARTH + self.altitude).to("km")

    @property
    def period(self):
        """The orbital period, from Kepler's third law, in s."""
        return (2 * np.pi * (self.radius**3 / MU_EARTH) ** 0.5).to("s")

    @property
    def orbits_per_day(self):
        """The orbits in one day, dimensionless."""
        return (Q_(1, "day") / self.period).to(u.dimensionless_unscaled)

    @property
    def velocity(self):
        """The circular orbital velocity, in km/s."""
        return ((MU_EARTH / self.radius) ** 0.5).to("km/s")

    @property
    def ground_track_speed(self):
        """
        The speed of the point below the satellite over a non-rotating Earth, in km/s.
        """
        return (self.velocity * R_EARTH / self.radius).to("km/s")
