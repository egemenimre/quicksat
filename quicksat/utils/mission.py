# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The mission, and the quantities every budget derives from it.

The mission is shared. The data budget needs the period and the orbits in a day. Delta-V
needs the circular velocity and the design life. Agility needs the ground track speed.
Each fact is stated once, and the rest is derived here, so the budgets cannot disagree.
They would disagree as soon as the same altitude was copied into three config files, and
then changed in only one of them.

Where the spacecraft is and how long it flies are both here for the same reason: more
than one module can use them. A fact that only one module uses stays in that module's
own config, such as the Isp in delta_v_config.yaml.

The orbit is circular throughout. Nothing here models eccentricity, perturbations
or drag.

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
        Height above the Earth's equatorial radius, `R_EARTH`
    inclination : Quantity
        Orbit plane inclination. Read only by calculations that change the plane
    duration : Quantity
        Design life. Scales the recurring delta-V manoeuvres, and the power and
        radiator work will need it too.
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    altitude: LengthQty
    inclination: AngleQty
    duration: TimeQty

    @property
    def radius(self):
        """
        Orbit radius, measured from the centre of the Earth.

        Returns
        -------
        radius : Quantity
        """
        return (R_EARTH + self.altitude).to("km")

    @property
    def period(self):
        """
        Orbital period, from Kepler's third law.

        Returns
        -------
        period : Quantity
        """
        return (2 * np.pi * (self.radius**3 / MU_EARTH) ** 0.5).to("s")

    @property
    def orbits_per_day(self):
        """
        Revolutions completed in one day.

        Dimensionless rather than a rate, because it turns a quantity per orbit into
        a quantity per day.

        Returns
        -------
        orbits_per_day : Quantity
        """
        return (Q_(1, "day") / self.period).to(u.dimensionless_unscaled)

    @property
    def velocity(self):
        """
        Circular orbital velocity.

        Returns
        -------
        velocity : Quantity
        """
        return ((MU_EARTH / self.radius) ** 0.5).to("km/s")

    @property
    def ground_track_speed(self):
        """
        Speed of the sub-satellite point over a non-rotating Earth.

        The orbital velocity scaled by the ratio of the Earth's radius to the orbit
        radius. Earth rotation is not included, so this is the speed along the
        ground track rather than relative to a fixed point on the surface.

        Returns
        -------
        speed : Quantity
        """
        return (self.velocity * R_EARTH / self.radius).to("km/s")
