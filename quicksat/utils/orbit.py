# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The orbit, and the quantities every budget derives from it.

The orbit is shared: the data budget needs the period and the orbits in a day,
delta-V needs the circular velocity, agility needs the ground track speed. Stating
the altitude once and deriving the rest here keeps the three from drifting apart,
which is what happens the first time the same altitude is copied into three config
files and one of them is retuned.

Circular throughout. Nothing here models eccentricity, perturbations or drag.

"""

import math
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from quicksat import MU_EARTH, Q_, R_EARTH
from quicksat.utils.parser_helpers import AngleQty, LengthQty


class Orbit(BaseModel):
    """
    A circular Earth orbit.

    Parameters
    ----------
    altitude : Quantity
        Height above the WGS-84 equatorial radius
    inclination : Quantity
        Orbit plane inclination; read only by calculations that change the plane
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    altitude: LengthQty
    inclination: AngleQty

    @classmethod
    def from_yaml_file(cls, file_path: Path) -> "Orbit":
        """
        Initialise the orbit from a YAML file.

        Parameters
        ----------
        file_path : Path
            Filepath containing the orbit data (YAML)

        Returns
        -------
        orbit : Orbit
            Orbit object from the input data
        """
        if not file_path:
            raise ValueError("Path is None. No file to be found.")
        elif not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        else:
            with open(file_path, "rt") as file:
                return cls.from_yaml_text(file.read())

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "Orbit":
        """
        Initialise the orbit from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the orbit data (YAML)

        Returns
        -------
        orbit : Orbit
            Orbit object from the input data
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
        return (2 * math.pi * (self.radius**3 / MU_EARTH) ** 0.5).to("s")

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
