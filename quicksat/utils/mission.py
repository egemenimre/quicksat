# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The mission, and the quantities every budget derives from it.

The mission is shared: the data budget needs the period and the orbits in a day,
delta-V needs the circular velocity and the design life, agility needs the ground
track speed. Stating each fact once and deriving the rest here keeps the budgets
from drifting apart, which is what happens the first time the same altitude is
copied into three config files and one of them is retuned.

Where the spacecraft is and how long it flies are both here for the same reason:
more than one module can use either. A fact only one module can use stays in that
module's own config -- the Isp in delta_v_config.yaml, say.

The orbit is circular throughout. Nothing here models eccentricity, perturbations
or drag.

"""

import os
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict

from quicksat import MU_EARTH, Q_, R_EARTH
from quicksat.utils.parser_helpers import AngleQty, LengthQty, TimeQty


class Mission(BaseModel):
    """
    A mission: a circular Earth orbit, and how long it is flown.

    Parameters
    ----------
    altitude : Quantity
        Height above the WGS-84 equatorial radius
    inclination : Quantity
        Orbit plane inclination; read only by calculations that change the plane
    duration : Quantity
        Design life. Scales the recurring delta-V manoeuvres, and the power and
        radiator work will want it too.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    altitude: LengthQty
    inclination: AngleQty
    duration: TimeQty

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "Mission":
        """
        Initialise the mission from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Filepath containing the mission data (YAML)

        Returns
        -------
        mission : Mission
            Mission object from the input data
        """
        if not file_path:
            raise ValueError("Path is None. No file to be found.")
        elif not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        else:
            with open(file_path, "rt") as file:
                return cls.from_yaml_text(file.read())

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "Mission":
        """
        Initialise the mission from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the mission data (YAML)

        Returns
        -------
        mission : Mission
            Mission object from the input data
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        return cls(**yaml.safe_load(yaml_text))

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

        Dimensionless rather than a rate, because it is used to turn a per-orbit
        quantity into a per-day one.

        Returns
        -------
        orbits_per_day : Quantity
        """
        return (Q_(1, "day") / self.period).to("dimensionless")

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
