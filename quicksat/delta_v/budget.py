# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Delta-V budget: what the mission has to spend to fly its orbit.

Each manoeuvre turns Mission Analysis's numbers into a delta-V with a short closed form,
for circular orbits and two-impulse transfers. `docs/sizing/delta_v_ref.ipynb` explains
the forms and their limits.

"""

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import numpy as np
import pandas as pd

# astropy.constants creates its constants at import, so pyright cannot see them
from astropy.constants import g0  # pyright: ignore[reportAttributeAccessIssue]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quicksat import MU_EARTH, Q_, R_EARTH, u
from quicksat.delta_v.report import tabulate
from quicksat.utils.checks import Check
from quicksat.utils.mission import Mission

if TYPE_CHECKING:  # a type annotation only, so quicksat.mass stays unimported
    from quicksat.mass.budget import MassBudget

from quicksat.utils.parser_helpers import (
    Commented,
    NoSpaceStr,
    PlainQty,
    TimeQty,
    YamlFile,
    read_csv_rows,
    validated_rows,
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
    "loss_factor",
    "comments",
)


class ManoeuvreType(str, Enum):
    """How a manoeuvre's delta-V is worked out from its `value`."""

    ALTITUDE_CHANGE = "altitude_change"
    """Hohmann transfer between two circular altitudes. `value` is the change."""

    COLLISION_AVOIDANCE = "collision_avoidance"
    """The same Hohmann, doubled for a return burn. `value` is the altitude offset."""

    INCLINATION_CHANGE = "inclination_change"
    """Plane change at circular velocity. `value` is the angle."""

    DEORBIT = "deorbit"
    """One impulse lowering perigee. `value` is the target perigee altitude."""

    GIVEN = "given"
    """Taken as-is. `value` is the delta-V itself."""


_DIMENSIONS = {
    ManoeuvreType.ALTITUDE_CHANGE: (u.m, "length"),
    ManoeuvreType.COLLISION_AVOIDANCE: (u.m, "length"),
    ManoeuvreType.INCLINATION_CHANGE: (u.deg, "angle"),
    ManoeuvreType.DEORBIT: (u.m, "length"),
    ManoeuvreType.GIVEN: (u.m / u.s, "velocity"),
}


class Manoeuvre(BaseModel):
    """One line of the delta-V budget, validated as it is read."""

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
    """How many times. Per year when `recurring`, otherwise for the whole mission."""

    recurring: bool = False
    """When set, `count` is per year and is multiplied by the mission duration."""

    loss_factor: Annotated[float, Field(ge=1.0)] = 1.0
    """The finite-burn and gravity losses, as a factor of at least 1.0 on the
    closed-form delta-V."""

    comments: str = ""
    """Free text notes."""

    @model_validator(mode="after")
    def _value_matches_the_type(self):
        """Checks that `value` has the dimension its manoeuvre type needs."""
        unit, label = _DIMENSIONS[self.manoeuvre_type]
        if not unit.is_equivalent(self.value.unit):
            article = "an" if label[0] in "aeiou" else "a"
            raise ValueError(
                f"A '{self.manoeuvre_type.value}' manoeuvre needs {article} {label} "
                f"in its value column, got '{self.value}'"
            )
        return self


class Propulsion(Commented):
    """What the propulsion system delivers, for the rocket equation."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    isp: TimeQty


class CollisionAvoidance(Commented):
    """Policy for how a collision avoidance manoeuvre is flown."""

    model_config = ConfigDict(extra="forbid")

    return_burn: bool = True
    """Up and back down. False when the raise was due anyway."""


class DeltaVConfig(YamlFile):
    """
    The budget's settings. The orbit and the mission's length are in the mission file.
    """

    model_config = ConfigDict(extra="forbid")

    propulsion: Propulsion
    margin: Annotated[float, Field(ge=0)] = 0.0
    """One allowance on the total, as a percentage."""

    collision_avoidance: CollisionAvoidance = CollisionAvoidance()


def hohmann_deltav(radius_1, radius_2):
    """
    Total delta-V of a two-impulse transfer between two circular orbits.

    Parameters
    ----------
    radius_1, radius_2 : Quantity
        The orbits' radii, from the Earth's centre

    Returns
    -------
    deltav : Quantity
        The sum of the two impulses, in m/s
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
        In m/s
    """
    return (2 * velocity * np.sin(angle / 2)).to("m/s")


def deorbit_deltav(radius, perigee_radius):
    """
    Delta-V of the one impulse that lowers the perigee to a re-entry altitude.

    Parameters
    ----------
    radius : Quantity
        The circular orbit's radius
    perigee_radius : Quantity
        The target perigee's radius

    Returns
    -------
    deltav : Quantity
        In m/s
    """
    velocity = (MU_EARTH / radius) ** 0.5
    ratio = (2 * perigee_radius / (radius + perigee_radius)) ** 0.5
    return (velocity * abs(1 - ratio)).to("m/s")


class DeltaVBudget:
    """
    A delta-V budget from a flat list of manoeuvres, with one margin on the total.

    Parameters
    ----------
    manoeuvres : list of Manoeuvre
        The manoeuvres
    config : DeltaVConfig
        The propulsion and the margin
    mission : Mission
        The shared mission: the orbit, and the duration for recurring manoeuvres
    mass_budget : MassBudget, optional
        The spacecraft, for the dry mass in `propellant_mass`
    """

    def __init__(
        self,
        manoeuvres: list[Manoeuvre],
        config: DeltaVConfig,
        mission: Mission,
        mass_budget: "MassBudget | None" = None,
    ):
        self.config = config
        self.mission = mission
        self.mass_budget = mass_budget
        self._frame = _frame_from_items(manoeuvres)

    @classmethod
    def from_csv(
        cls,
        csv_path: str | Path,
        config_path: str | Path,
        mission_path: str | Path,
        mass_budget: "MassBudget | None" = None,
    ) -> "DeltaVBudget":
        """
        Build a delta-V budget from its files.

        Parameters
        ----------
        csv_path : str or Path
            The manoeuvre list
        config_path, mission_path : str or Path
            The budget's config and the shared mission
        mass_budget : MassBudget, optional
            The spacecraft, for `propellant_mass`

        Returns
        -------
        budget : DeltaVBudget
            The budget
        """
        config = DeltaVConfig.from_yaml_file(Path(config_path))
        mission = Mission.from_yaml_file(Path(mission_path))
        raw = read_csv_rows(csv_path, REQUIRED_COLUMNS)
        manoeuvres = validated_rows(
            Manoeuvre, raw.to_dict("records"), Path(csv_path).name
        )

        return cls(manoeuvres, config, mission, mass_budget)

    @property
    def manoeuvre_table(self) -> pd.DataFrame:
        """A copy of the manoeuvre list."""
        return self._frame.copy()

    def resolve(self) -> pd.DataFrame:
        """
        The manoeuvre table with each row's delta-V.

        Returns
        -------
        frame : pd.DataFrame
            The manoeuvres, with `occurrences`, and `deltav_each` and `deltav_total` in
            m/s, losses included
        """
        frame = self._frame
        years = self.mission.duration.to_value("yr")

        row: Any  # itertuples() fields are columns, invisible to a checker
        each, occurrences = [], []
        for row in frame.itertuples():
            each.append(self._manoeuvre_deltav(row) * row.loss_factor)
            occurrences.append(row.count * (years if row.recurring else 1))

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
            Add the config's margin

        Returns
        -------
        deltav : Quantity
            In m/s
        """
        total = self.resolve()["deltav_total"].sum()
        if margin:
            total *= 1 + self.config.margin / 100.0
        return Q_(total, "m/s")

    def by_phase(self, margin: bool = True) -> pd.DataFrame:
        """
        Delta-V by mission phase.

        Parameters
        ----------
        margin : bool
            Add the config's margin

        Returns
        -------
        grouped : pd.DataFrame
            One row per phase, with `deltav` in m/s
        """
        return self._grouped("phase", margin)

    def by_type(self, margin: bool = True) -> pd.DataFrame:
        """
        Delta-V by manoeuvre type.

        Parameters
        ----------
        margin : bool
            Add the config's margin

        Returns
        -------
        grouped : pd.DataFrame
            One row per type, with `deltav` in m/s
        """
        return self._grouped("manoeuvre_type", margin)

    def propellant_mass(self, dry_mass=None, margin: bool = True):
        """
        Propellant needed to deliver the budget, from the rocket equation.

        The dry mass is the mass budget's in orbit with empty tanks, unless one is
        passed in. Nothing is written back.

        Parameters
        ----------
        dry_mass : Quantity, optional
            The mass with no propellant, after the last burn
        margin : bool
            Add the config's margin to the delta-V

        Returns
        -------
        mass : Quantity
            In kg

        Raises
        ------
        ValueError
            If there is neither a dry mass nor a mass budget
        """
        if dry_mass is None:
            if self.mass_budget is None:
                raise ValueError(
                    "No dry mass given and no mass budget attached. Pass a dry mass, "
                    "or build the delta-V budget with mass_budget=... to take it "
                    "from there."
                )
            dry_mass = self.mass_budget.in_orbit_mass(propellant=0)
        exhaust_velocity = self.config.propulsion.isp * g0
        ratio = (self.total_deltav(margin) / exhaust_velocity).to(
            u.dimensionless_unscaled
        )
        return (dry_mass * (np.exp(ratio) - 1)).to("kg")

    def checks(self) -> list[Check]:
        """
        The check: the propellant loaded, from the mass budget, against the propellant
        required.

        Returns
        -------
        checks : list of Check
            The check, or none without a mass budget
        """
        if self.mass_budget is None:
            return []
        return [
            Check(
                "propellant",
                "The propellant loaded covers the propellant required",
                self.mass_budget.propellant_mass(),
                self.propellant_mass(),
            )
        ]

    def tabulated_deltav(
        self,
        margin: bool = True,
        comments: bool = False,
        loss_factor: bool = False,
    ):
        """
        The budget as a document: every manoeuvre, with subtotals by phase.

        Parameters
        ----------
        margin : bool
            Show the margin and the total with it
        comments : bool
            Show the comments column
        loss_factor : bool
            Show each manoeuvre's loss factor

        Returns
        -------
        report : Styler
            One row per manoeuvre and per subtotal
        """
        return tabulate(self.resolve(), self.config, margin, comments, loss_factor)

    def _grouped(self, column: str, margin: bool) -> pd.DataFrame:
        """The resolved delta-V summed over one column, with or without the margin."""
        grouped = cast(
            pd.DataFrame,
            self.resolve().groupby(column, sort=True)[["deltav_total"]].sum(),
        )
        if margin:
            grouped["deltav_total"] *= 1 + self.config.margin / 100.0
        return grouped.rename(columns={"deltav_total": "deltav"})

    def _manoeuvre_deltav(self, row: Any) -> float:
        """One manoeuvre's delta-V before its count, in m/s."""
        radius = self.mission.radius
        kind = ManoeuvreType(row.manoeuvre_type)

        if kind is ManoeuvreType.GIVEN:
            return row.value.to_value("m/s")
        if kind is ManoeuvreType.INCLINATION_CHANGE:
            return plane_change_deltav(self.mission.velocity, row.value).to_value("m/s")
        if kind is ManoeuvreType.DEORBIT:
            return deorbit_deltav(radius, R_EARTH + row.value).to_value("m/s")

        hop = hohmann_deltav(radius, radius + row.value).to_value("m/s")
        if kind is ManoeuvreType.COLLISION_AVOIDANCE and (
            self.config.collision_avoidance.return_burn
        ):
            return 2 * hop
        return hop


def _frame_from_items(manoeuvres: list[Manoeuvre]) -> pd.DataFrame:
    """
    The manoeuvres as the working table, with `value` kept as a Quantity, since its unit
    varies by row.
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
            "loss_factor": item.loss_factor,
            "comments": item.comments,
        }
        for item in manoeuvres
    ]
    frame = pd.DataFrame(records, columns=list(_FRAME_COLUMNS))
    frame["count"] = frame["count"].astype(float)
    frame["recurring"] = frame["recurring"].astype(bool)
    frame["loss_factor"] = frame["loss_factor"].astype(float)
    return frame
