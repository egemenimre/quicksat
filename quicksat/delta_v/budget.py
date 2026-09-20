# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Delta-V budget: what the mission has to spend to fly its orbit.

Mission Analysis owns the orbital mechanics. This module holds their numbers --
how many collision avoidance manoeuvres a year, what the injection dispersion is,
what altitude to deorbit from -- and does the small closed-form calculation that
turns each into a delta-V.

Circular orbits throughout, two-impulse transfers, no perturbations. Anything that
needs real analysis arrives as a `given` manoeuvre with the delta-V already worked
out elsewhere.

"""

import os
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, cast

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from quicksat import MU_EARTH, Q_, R_EARTH
from quicksat.delta_v.report import tabulate
from quicksat.utils.orbit import Orbit
from quicksat.utils.parser_helpers import (
    NoSpaceStr,
    PlainQty,
    TimeQty,
)

REQUIRED_COLUMNS = (
    "manoeuvre_id",
    "manoeuvre_name",
    "phase",
    "manoeuvre_type",
    "value",
    "count",
)

_FRAME_COLUMNS = (
    "manoeuvre_id",
    "manoeuvre_name",
    "phase",
    "manoeuvre_type",
    "value",
    "count",
    "recurring",
    "comments",
)


class ManoeuvreType(str, Enum):
    """How a manoeuvre's delta-V is worked out from its `value`."""

    ALTITUDE_CHANGE = "altitude_change"
    """Hohmann transfer between two circular altitudes. `value` is the change."""

    COLLISION_AVOIDANCE = "collision_avoidance"
    """The same Hohmann, doubled when the config says the hop returns.
    `value` is the altitude offset."""

    INCLINATION_CHANGE = "inclination_change"
    """Plane change at circular velocity. `value` is the angle."""

    DEORBIT = "deorbit"
    """One impulse lowering perigee. `value` is the target perigee altitude."""

    GIVEN = "given"
    """Taken as-is. `value` is the delta-V itself."""


_DIMENSIONS = {
    ManoeuvreType.ALTITUDE_CHANGE: ("[length]", "length"),
    ManoeuvreType.COLLISION_AVOIDANCE: ("[length]", "length"),
    ManoeuvreType.INCLINATION_CHANGE: ("", "angle"),
    ManoeuvreType.DEORBIT: ("[length]", "length"),
    ManoeuvreType.GIVEN: ("[length]/[time]", "velocity"),
}


class Manoeuvre(BaseModel):
    """
    One line of the delta-V budget.

    Validated row by row on load, so a malformed CSV reports the offending row and
    field rather than failing later in the arithmetic.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    manoeuvre_id: NoSpaceStr
    """Short identifier, no whitespace (`collision_avoidance`)."""

    manoeuvre_name: str
    """Full name, free text."""

    phase: NoSpaceStr
    """Mission phase, the reporting axis (`Commissioning`, `Operations`, `Disposal`)."""

    manoeuvre_type: ManoeuvreType
    """Which closed form turns `value` into a delta-V."""

    value: PlainQty
    """The input, with its unit. What it means is set by `manoeuvre_type`."""

    count: Annotated[float, Field(ge=0)]
    """How many times. Per year when `recurring`, otherwise outright."""

    recurring: bool = False
    """When set, `count` is per year and is multiplied by the mission duration."""

    comments: str = ""
    """Free text notes."""

    @model_validator(mode="after")
    def _value_matches_the_type(self):
        """
        Checks `value` carries the dimension its manoeuvre type requires.

        This is the point of one `value` column serving five types: a length where
        a velocity belongs is caught at the row that holds it, rather than becoming
        a number that happens to be wrong.
        """
        dimension, label = _DIMENSIONS[self.manoeuvre_type]
        if not self.value.check(dimension):
            article = "an" if label[0] in "aeiou" else "a"
            raise ValueError(
                f"A '{self.manoeuvre_type.value}' manoeuvre needs {article} {label} "
                f"in its value column, got '{self.value}'"
            )
        return self


class Mission(BaseModel):
    """How long the mission lasts, for scaling the recurring manoeuvres."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    duration: TimeQty


class Propulsion(BaseModel):
    """What the propulsion system delivers, for the rocket equation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    isp: TimeQty


class CollisionAvoidance(BaseModel):
    """Policy for how a collision avoidance hop is flown."""

    return_burn: bool = True
    """A hop up and back down. False when the satellite was due to be raised
    anyway and the manoeuvre does double duty against the maintenance debt."""


class DeltaVConfig(BaseModel):
    """
    Budget settings.

    The orbit is not here: it comes from the shared orbit file, because delta-V is
    not the only budget that needs it.
    """

    mission: Mission
    propulsion: Propulsion
    margin: Annotated[float, Field(ge=0)] = 0.0
    """One allowance on the total, as a percentage. Per-manoeuvre contingency is
    not a meaningful quantity when the counts themselves are the uncertain part."""

    collision_avoidance: CollisionAvoidance = CollisionAvoidance()

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "DeltaVConfig":
        """
        Initialise the config from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Filepath containing the config data (YAML)

        Returns
        -------
        config : DeltaVConfig
            Config object from the input data
        """
        if not file_path:
            raise ValueError("Path is None. No file to be found.")
        elif not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        else:
            with open(file_path, "rt") as file:
                return cls.from_yaml_text(file.read())

    @classmethod
    def from_yaml_text(cls, yaml_text: str) -> "DeltaVConfig":
        """
        Initialise the config from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the config data (YAML)

        Returns
        -------
        config : DeltaVConfig
            Config object from the input data
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        return cls(**yaml.safe_load(yaml_text))


def hohmann_deltav(radius_1, radius_2):
    """
    Total delta-V of a two-impulse transfer between two circular orbits.

    Parameters
    ----------
    radius_1, radius_2 : Quantity
        Orbit radii, measured from the centre of the Earth

    Returns
    -------
    deltav : Quantity
        The sum of the two impulses, always positive
    """
    velocity_1 = (MU_EARTH / radius_1) ** 0.5
    velocity_2 = (MU_EARTH / radius_2) ** 0.5
    transfer = radius_1 + radius_2
    first = velocity_1 * abs((2 * radius_2 / transfer) ** 0.5 - 1)
    second = velocity_2 * abs(1 - (2 * radius_1 / transfer) ** 0.5)
    return (first + second).to("m/s")


def plane_change_deltav(velocity, angle):
    """
    Delta-V of a plane change flown at circular velocity.

    Parameters
    ----------
    velocity : Quantity
        Circular orbital velocity
    angle : Quantity
        Inclination change

    Returns
    -------
    deltav : Quantity
    """
    return (2 * velocity * np.sin(angle / 2)).to("m/s")


def deorbit_deltav(radius, perigee_radius):
    """
    Delta-V of the single impulse that lowers perigee to a re-entry altitude.

    Parameters
    ----------
    radius : Quantity
        Starting circular orbit radius
    perigee_radius : Quantity
        Target perigee radius

    Returns
    -------
    deltav : Quantity
    """
    velocity = (MU_EARTH / radius) ** 0.5
    ratio = (2 * perigee_radius / (radius + perigee_radius)) ** 0.5
    return (velocity * abs(1 - ratio)).to("m/s")


class DeltaVBudget:
    """
    A delta-V budget assembled from a flat list of manoeuvres.

    Like the mass budget it is a table, and `phase` and `manoeuvre_type` are two
    ordinary columns to group over. Unlike the mass budget there is one margin
    rather than two: a single margin on the total, because per-manoeuvre delta-V
    contingency means little when the counts are the uncertain part.

    Parameters
    ----------
    manoeuvres : list[Manoeuvre]
        Validated manoeuvre items
    config : DeltaVConfig
        Mission duration, propulsion and the margin
    orbit : Orbit
        The shared orbit the manoeuvres are flown from
    """

    def __init__(self, manoeuvres: list[Manoeuvre], config: DeltaVConfig, orbit: Orbit):
        self.config = config
        self.orbit = orbit
        self._frame = _frame_from_items(manoeuvres)

    @classmethod
    def from_csv(
        cls, csv_path: str | Path, config_path: str | Path, orbit_path: str | Path
    ) -> "DeltaVBudget":
        """
        Build a delta-V budget from a manoeuvre CSV, a config and an orbit file.

        Where several budgets share one orbit, load it once with
        `Orbit.from_yaml_file` and use the constructor instead.

        Parameters
        ----------
        csv_path : str | Path
            Filepath of the manoeuvre list (CSV)
        config_path : str | Path
            Filepath of the budget config (YAML)
        orbit_path : str | Path
            Filepath of the shared orbit (YAML)

        Returns
        -------
        budget : DeltaVBudget
            The assembled budget
        """
        config = DeltaVConfig.from_yaml_file(Path(config_path))
        orbit = Orbit.from_yaml_file(Path(orbit_path))
        raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False)

        missing = [name for name in REQUIRED_COLUMNS if name not in raw.columns]
        if missing:
            raise ValueError(f"{csv_path}: missing columns {missing}")

        manoeuvres = []
        for row_number, record in enumerate(raw.to_dict("records"), start=2):
            try:
                manoeuvres.append(Manoeuvre(**record))
            except ValidationError as exc:
                raise ValueError(f"{csv_path}, row {row_number}:\n{exc}") from exc

        return cls(manoeuvres, config, orbit)

    @property
    def manoeuvre_table(self) -> pd.DataFrame:
        """
        The validated manoeuvre list.

        Returns
        -------
        frame : pd.DataFrame
            A copy, so nothing downstream writes back into the budget
        """
        return self._frame.copy()

    def resolve(self) -> pd.DataFrame:
        """
        The manoeuvre table with the delta-V of each row worked out.

        Returns
        -------
        frame : pd.DataFrame
            The manoeuvres, with `deltav_each` and `deltav_total` columns in m/s
            and the effective `occurrences` the count resolves to
        """
        frame = self._frame
        years = self.config.mission.duration.to("year").magnitude

        each = [self._manoeuvre_deltav(row) for row in frame.itertuples()]
        occurrences = [
            row.count * (years if row.recurring else 1) for row in frame.itertuples()
        ]
        return frame.assign(
            deltav_each=each,
            occurrences=occurrences,
            deltav_total=[e * n for e, n in zip(each, occurrences, strict=True)],
        )

    def total_deltav(self, margin: bool = True):
        """
        Total delta-V for the mission.

        Parameters
        ----------
        margin : bool
            Apply the config's margin on top

        Returns
        -------
        deltav : Quantity
        """
        total = self.resolve()["deltav_total"].sum()
        if margin:
            total *= 1 + self.config.margin / 100.0
        return Q_(total, "m/s")

    def by_phase(self, margin: bool = True) -> pd.DataFrame:
        """
        Delta-V grouped by mission phase.

        Parameters
        ----------
        margin : bool
            Apply the config's margin on top

        Returns
        -------
        grouped : pd.DataFrame
            One row per phase, with a single `deltav` column in m/s
        """
        return self._grouped("phase", margin)

    def by_type(self, margin: bool = True) -> pd.DataFrame:
        """
        Delta-V grouped by manoeuvre type.

        Parameters
        ----------
        margin : bool
            Apply the config's margin on top

        Returns
        -------
        grouped : pd.DataFrame
            One row per manoeuvre type, with a single `deltav` column in m/s
        """
        return self._grouped("manoeuvre_type", margin)

    def propellant_mass(self, dry_mass, margin: bool = True):
        """
        Propellant needed to deliver the budget, from the rocket equation.

        Takes the dry mass as an argument rather than reaching for a `MassBudget`,
        so the two modules stay decoupled and the sizing loop is closed where it can
        be seen. Nothing is written back: the equipment CSV stays the source of
        truth for what is actually loaded.

        Parameters
        ----------
        dry_mass : Quantity
            Spacecraft mass with no propellant aboard, the final mass of the burn
        margin : bool
            Include the config's margin in the delta-V

        Returns
        -------
        mass : Quantity
            Propellant required
        """
        exhaust_velocity = self.config.propulsion.isp * Q_(1, "standard_gravity")
        ratio = (self.total_deltav(margin) / exhaust_velocity).to("dimensionless")
        return (dry_mass * (np.exp(ratio) - 1)).to("kg")

    def tabulated_deltav(self, margin: bool = True, comments: bool = False):
        """
        The budget as a document: every manoeuvre, with subtotals by phase.

        Parameters
        ----------
        margin : bool
            Show the margin line and the total that includes it
        comments : bool
            Show the manoeuvre file's comments column

        Returns
        -------
        report : Styler
            One row per manoeuvre and per subtotal, rendered for reading
        """
        return tabulate(self.resolve(), self.config, margin, comments)

    def _grouped(self, column: str, margin: bool) -> pd.DataFrame:
        """
        Sums the resolved delta-V over one grouping axis.

        Parameters
        ----------
        column : str
            The column to group on
        margin : bool
            Apply the config's margin on top

        Returns
        -------
        grouped : pd.DataFrame
            One row per distinct value, with a single `deltav` column
        """
        grouped = cast(
            pd.DataFrame,
            self.resolve().groupby(column, sort=True)[["deltav_total"]].sum(),
        )
        if margin:
            grouped["deltav_total"] *= 1 + self.config.margin / 100.0
        return grouped.rename(columns={"deltav_total": "deltav"})

    def _manoeuvre_deltav(self, row: Any) -> float:
        """
        Delta-V of one manoeuvre, in m/s, before any count is applied.

        Parameters
        ----------
        row : namedtuple
            One row of the manoeuvre frame

        Returns
        -------
        deltav : float
            Magnitude in m/s
        """
        radius = self.orbit.radius
        kind = ManoeuvreType(row.manoeuvre_type)

        if kind is ManoeuvreType.GIVEN:
            return row.value.to("m/s").magnitude
        if kind is ManoeuvreType.INCLINATION_CHANGE:
            return plane_change_deltav(self.orbit.velocity, row.value).magnitude
        if kind is ManoeuvreType.DEORBIT:
            return deorbit_deltav(radius, R_EARTH + row.value).magnitude

        hop = hohmann_deltav(radius, radius + row.value).magnitude
        if kind is ManoeuvreType.COLLISION_AVOIDANCE and (
            self.config.collision_avoidance.return_burn
        ):
            return 2 * hop
        return hop


def _frame_from_items(manoeuvres: list[Manoeuvre]) -> pd.DataFrame:
    """
    Flattens validated manoeuvres into the working table.

    `value` stays a pint Quantity rather than being reduced to a float: unlike the
    mass budget's single dimension, these are lengths, angles and velocities in one
    column, so there is no canonical unit to convert to.

    Parameters
    ----------
    manoeuvres : list[Manoeuvre]
        Validated manoeuvre items

    Returns
    -------
    frame : pd.DataFrame
        One row per manoeuvre
    """
    records = [
        {
            "manoeuvre_id": item.manoeuvre_id,
            "manoeuvre_name": item.manoeuvre_name,
            "phase": item.phase,
            "manoeuvre_type": item.manoeuvre_type.value,
            "value": item.value,
            "count": item.count,
            "recurring": item.recurring,
            "comments": item.comments,
        }
        for item in manoeuvres
    ]
    frame = pd.DataFrame(records, columns=list(_FRAME_COLUMNS))
    frame["count"] = frame["count"].astype(float)
    frame["recurring"] = frame["recurring"].astype(bool)
    return frame
