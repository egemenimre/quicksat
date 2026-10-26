# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Mass budget: a flat equipment list, summed by location, responsibility or subsystem.

`docs/sizing/mass_budget_ref.ipynb` explains the budget, its margins and its limits.

"""

from pathlib import Path
from typing import Annotated, cast

import pandas as pd
from pandas.io.formats.style import Styler
from pydantic import BeforeValidator, ConfigDict, Field

from quicksat import Q_
from quicksat.mass.equipment import Equipment, MassClass
from quicksat.mass.report import tabulate
from quicksat.utils.parser_helpers import (
    Commented,
    YamlFile,
    read_csv_rows,
    validated_rows,
    without_comments,
)

LAUNCHER_LOCATION = "Launcher"
"""Reserved location name for hardware that stays with the launch vehicle."""

PLATFORM_LOCATION = "Platform"
"""Conventional name for the satellite bus, used by `MassBudget.platform_mass`."""

PAYLOAD_LOCATION = "Payload"
"""Conventional name for the payload, used by `MassBudget.payload_mass`."""

HARNESS_SUBSYSTEM = "Harness"
"""Subsystem tag given to the derived harness rows."""


REQUIRED_COLUMNS = (
    "equipment_id",
    "equipment_name",
    "location",
    "responsibility",
    "subsystem",
    "unit_mass",
    "eqpt_margin",
    "number_of_units",
)

_FRAME_COLUMNS = (
    "equipment_id",
    "equipment_name",
    "location",
    "responsibility",
    "subsystem",
    "eqpt_mass",
    "eqpt_margin",
    "number_of_units",
    "mass_class",
    "comments",
    "eqpt_total_mass",
)


class LocationConfig(Commented):
    """Margin and harness settings for a single location."""

    model_config = ConfigDict(extra="forbid")

    system_margin: float = Field(default=0.0, ge=0)
    """System margin for this location, as a percentage, applied to its subtotal."""

    harness_fraction: float = Field(default=0.0, ge=0)
    """Harness mass as a percentage of this location's equipment mass, before margin."""

    harness_margin: float = Field(default=0.0, ge=0)
    """Contingency on the derived harness mass, as a percentage."""

    retained_in_orbit: bool = True
    """Whether hardware here survives separation."""


_LAUNCHER_DEFAULT = LocationConfig(retained_in_orbit=False)


class MassBudgetConfig(YamlFile):
    """The budget's settings, by location, which holds both margins and the harness."""

    model_config = ConfigDict(extra="forbid")

    locations: Annotated[
        dict[str, LocationConfig], BeforeValidator(without_comments)
    ] = Field(default_factory=dict)

    def for_location(self, name: str) -> LocationConfig:
        """
        Settings for a location. `Launcher` needs no entry, and any other unlisted
        location is refused.

        Parameters
        ----------
        name : str
            The location's name

        Returns
        -------
        location_config : LocationConfig
            Its settings
        """
        config = self.locations.get(name)
        if config is not None:
            return config
        if name == LAUNCHER_LOCATION:
            return _LAUNCHER_DEFAULT
        raise ValueError(
            f"Location '{name}' is used in the equipment list but is missing from "
            f"the budget config. Add it under 'locations:'."
        )


class MassBudget:
    """
    A satellite mass budget, as a table over a flat equipment list.

    Every query takes the same four flags. Their defaults describe the satellite at the
    start of life:

    - `propellant`: the percentage of the propellant load to count, 100 at the start of
      life and 0 at the end.
    - `sys_margin`: add each location's system margin.
    - `eqpt_margin`: add each item's equipment margin.
    - `in_orbit`: leave out the hardware that stays with the launcher.

    Parameters
    ----------
    equipment : list of Equipment
        The equipment items
    config : MassBudgetConfig
        The margins and the harness, by location
    """

    def __init__(self, equipment: list[Equipment], config: MassBudgetConfig):
        """Checks the locations and adds the harness rows."""
        self.config = config
        frame = _frame_from_items(equipment)
        _check_duplicates(frame)
        for location in frame["location"].unique():
            config.for_location(location)
        self._frame = pd.concat(
            [frame, _harness_frame(frame, config)], ignore_index=True
        )

    @classmethod
    def from_csv(cls, csv_path: str | Path, config_path: str | Path) -> "MassBudget":
        """
        Build a mass budget from its files.

        Parameters
        ----------
        csv_path : str or Path
            The equipment list
        config_path : str or Path
            The budget's config

        Returns
        -------
        budget : MassBudget
            The budget
        """
        config = MassBudgetConfig.from_yaml_file(Path(config_path))
        raw = read_csv_rows(csv_path, REQUIRED_COLUMNS)
        equipment = validated_rows(
            Equipment, raw.to_dict("records"), Path(csv_path).name
        )

        return cls(equipment, config)

    @property
    def eqpt_table(self) -> pd.DataFrame:
        """A copy of the equipment table, harness rows included."""
        return self._frame.copy()

    def resolve(
        self,
        propellant: float = 100.0,
        in_orbit: bool = True,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
    ) -> pd.DataFrame:
        """
        The equipment table for one case, with each row's `mass` from the flags.

        Parameters
        ----------
        propellant : float
            The percentage of the propellant load to count
        in_orbit : bool
            Leave out the launcher's hardware
        sys_margin : bool
            Add the system margins
        eqpt_margin : bool
            Add the equipment margins

        Returns
        -------
        frame : pd.DataFrame
            The rows kept, with a `mass` column in kg
        """
        if not 0.0 <= propellant <= 100.0:
            raise ValueError(
                f"propellant is a percentage of the load, so it must be between "
                f"0 and 100, got {propellant}"
            )

        frame = self._frame

        if in_orbit:
            retained = frame["location"].map(
                lambda name: self.config.for_location(name).retained_in_orbit
            )
            frame = frame[retained]

        return frame.assign(mass=self._mass(frame, sys_margin, eqpt_margin, propellant))  # pyright: ignore[reportArgumentType]

    def total_mass(
        self,
        propellant: float = 100.0,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
        in_orbit: bool = True,
    ):
        """
        Total mass, for any case of the flags.

        Parameters
        ----------
        propellant : float
            The percentage of the propellant load to count
        in_orbit : bool
            Leave out the launcher's hardware
        sys_margin : bool
            Add the system margins
        eqpt_margin : bool
            Add the equipment margins

        Returns
        -------
        mass : Quantity
            In kg
        """
        frame = self.resolve(
            propellant=propellant,
            in_orbit=in_orbit,
            sys_margin=sys_margin,
            eqpt_margin=eqpt_margin,
        )
        return Q_(frame["mass"].sum(), "kg")

    def in_orbit_mass(
        self,
        propellant: float = 100.0,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
    ):
        """
        Mass after separation, without the launcher's hardware.

        Parameters
        ----------
        propellant : float
            The percentage of the propellant load to count
        sys_margin : bool
            Add the system margins
        eqpt_margin : bool
            Add the equipment margins

        Returns
        -------
        mass : Quantity
            In kg
        """
        return self.total_mass(
            propellant=propellant,
            sys_margin=sys_margin,
            eqpt_margin=eqpt_margin,
            in_orbit=True,
        )

    def on_ground_mass(
        self,
        propellant: float = 100.0,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
    ):
        """
        Mass before separation, with the launcher's hardware.

        Parameters
        ----------
        propellant : float
            The percentage of the propellant load to count
        sys_margin : bool
            Add the system margins
        eqpt_margin : bool
            Add the equipment margins

        Returns
        -------
        mass : Quantity
            In kg
        """
        return self.total_mass(
            propellant=propellant,
            sys_margin=sys_margin,
            eqpt_margin=eqpt_margin,
            in_orbit=False,
        )

    def platform_mass(
        self,
        propellant: float = 100.0,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
        by_responsibility: bool = False,
    ):
        """
        Platform mass, by location or by responsibility.

        Parameters
        ----------
        propellant : float
            The percentage of the propellant load to count
        sys_margin : bool
            Add the system margins
        eqpt_margin : bool
            Add the equipment margins
        by_responsibility : bool
            Sum the rows whose responsibility is Platform, not whose location is

        Returns
        -------
        mass : Quantity
            In kg
        """
        return self._named_mass(
            PLATFORM_LOCATION, propellant, sys_margin, eqpt_margin, by_responsibility
        )

    def payload_mass(
        self,
        propellant: float = 100.0,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
        by_responsibility: bool = False,
    ):
        """
        Payload mass, by location or by responsibility.

        Parameters
        ----------
        propellant : float
            The percentage of the propellant load to count
        sys_margin : bool
            Add the system margins
        eqpt_margin : bool
            Add the equipment margins
        by_responsibility : bool
            Sum the rows whose responsibility is Payload, not whose location is

        Returns
        -------
        mass : Quantity
            In kg
        """
        return self._named_mass(
            PAYLOAD_LOCATION, propellant, sys_margin, eqpt_margin, by_responsibility
        )

    def subsystem_mass(self, subsys_id: str, eqpt_margin: bool = True):
        """
        Mass of one subsystem, with the full propellant load and no system margin.

        Parameters
        ----------
        subsys_id : str
            The subsystem's name, as in the equipment file
        eqpt_margin : bool
            Add the equipment margins

        Returns
        -------
        mass : Quantity
            In kg
        """
        frame = self.resolve(
            propellant=100.0, in_orbit=True, sys_margin=False, eqpt_margin=eqpt_margin
        )
        return Q_(frame.loc[frame["subsystem"] == subsys_id, "mass"].sum(), "kg")

    def propellant_mass(self):
        """
        The full propellant load, which takes no margin.

        Returns
        -------
        mass : Quantity
            In kg
        """
        frame = self._frame
        is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
        return Q_(frame.loc[is_propellant, "eqpt_total_mass"].sum(), "kg")

    def by_location(self, **kwargs) -> pd.DataFrame:
        """
        Mass by location.

        Parameters
        ----------
        **kwargs
            The query flags, passed to `resolve`

        Returns
        -------
        grouped : pd.DataFrame
            One row per location, with `mass` in kg
        """
        return self._grouped("location", **kwargs)

    def by_responsibility(self, **kwargs) -> pd.DataFrame:
        """
        Mass by responsibility.

        Parameters
        ----------
        **kwargs
            The query flags, passed to `resolve`

        Returns
        -------
        grouped : pd.DataFrame
            One row per responsibility, with `mass` in kg
        """
        return self._grouped("responsibility", **kwargs)

    def by_subsystem(self, **kwargs) -> pd.DataFrame:
        """
        Mass by subsystem.

        Parameters
        ----------
        **kwargs
            The query flags, passed to `resolve`

        Returns
        -------
        grouped : pd.DataFrame
            One row per subsystem, with `mass` in kg
        """
        return self._grouped("subsystem", **kwargs)

    def tabulated_mass(
        self,
        in_orbit: bool = True,
        subsystem_subtotals: bool = False,
        comments: bool = False,
    ) -> Styler:
        """
        The budget as a document: every item, with subtotals in reading order.

        The propellant comes once, at the end, so every subtotal above it is dry.

        Parameters
        ----------
        in_orbit : bool
            Leave out the launcher's block, for the in-orbit masses
        subsystem_subtotals : bool
            Add a subtotal after each subsystem
        comments : bool
            Show the comments column

        Returns
        -------
        report : Styler
            One row per item and per subtotal, with the frame as `.data`
        """
        return tabulate(
            self._frame, self.config, in_orbit, subsystem_subtotals, comments
        )

    def _named_mass(self, name, propellant, sys_margin, eqpt_margin, by_responsibility):
        """The mass of the rows of one location or responsibility, in kg."""
        frame = self.resolve(
            propellant=propellant,
            in_orbit=True,
            sys_margin=sys_margin,
            eqpt_margin=eqpt_margin,
        )
        column = "responsibility" if by_responsibility else "location"
        return Q_(frame.loc[frame[column] == name, "mass"].sum(), "kg")

    def _grouped(self, column: str, **kwargs) -> pd.DataFrame:
        """The resolved mass summed over one column."""
        frame = self.resolve(**kwargs)
        return cast(pd.DataFrame, frame.groupby(column, sort=True)[["mass"]].sum())

    def _mass(
        self,
        frame: pd.DataFrame,
        sys_margin: bool,
        eqpt_margin: bool,
        propellant: float,
    ):
        """Each row's mass for a case of the flags, built from the flags."""
        mass = frame["eqpt_total_mass"]
        if eqpt_margin:
            mass = mass * (1.0 + frame["eqpt_margin"] / 100.0)
        if sys_margin:
            mass = mass * frame["location"].map(
                lambda name: 1.0 + self.config.for_location(name).system_margin / 100.0
            )
        # propellant never takes a margin, whatever the flags say. It is used up over
        # the mission, rather than being present or absent
        is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
        return mass.mask(is_propellant, frame["eqpt_total_mass"] * propellant / 100.0)


def _frame_from_items(equipment: list[Equipment]) -> pd.DataFrame:
    """The equipment as the working table, with the masses as floats in kg."""
    records = []
    for item in equipment:
        eqpt_mass = item.unit_mass.to_value("kg")
        records.append(
            {
                "equipment_id": item.equipment_id,
                "equipment_name": item.equipment_name,
                "location": item.location,
                "responsibility": item.responsibility,
                "subsystem": item.subsystem,
                "eqpt_mass": eqpt_mass,
                "eqpt_margin": item.eqpt_margin,
                "number_of_units": item.number_of_units,
                "mass_class": item.mass_class.value,
                "comments": item.comments,
                "eqpt_total_mass": eqpt_mass * item.number_of_units,
            }
        )

    frame = pd.DataFrame(records, columns=list(_FRAME_COLUMNS))
    for column in ("eqpt_mass", "eqpt_margin", "eqpt_total_mass"):
        frame[column] = frame[column].astype(float)
    frame["number_of_units"] = frame["number_of_units"].astype(int)
    return frame


def _check_duplicates(frame: pd.DataFrame) -> None:
    """Refuses an equipment id repeated within one location."""
    duplicated = frame.duplicated(subset=["equipment_id", "location"], keep=False)
    if duplicated.any():
        pairs = (
            frame.loc[duplicated, ["equipment_id", "location"]]
            .drop_duplicates()
            .to_dict("records")
        )
        raise ValueError(f"Duplicate (equipment_id, location) pairs: {pairs}")


def _harness_frame(frame: pd.DataFrame, config: MassBudgetConfig) -> pd.DataFrame:
    """
    One harness row per location, from its equipment mass before margin and without
    propellant.
    """
    hardware = frame[frame["mass_class"] == MassClass.EQUIPMENT.value]
    records = []

    for location, group in hardware.groupby("location", sort=True):
        location_config = config.for_location(location)  # pyright: ignore[reportArgumentType]
        base_kg = group["eqpt_total_mass"].sum()
        harness_kg = base_kg * location_config.harness_fraction / 100.0
        if harness_kg <= 0:
            continue
        records.append(
            {
                "equipment_id": f"harness_{location.lower()}",  # pyright: ignore[reportAttributeAccessIssue]
                "equipment_name": f"{location} harness",
                "location": location,
                "responsibility": location,
                "subsystem": HARNESS_SUBSYSTEM,
                "eqpt_mass": harness_kg,
                "eqpt_margin": location_config.harness_margin,
                "number_of_units": 1,
                "mass_class": MassClass.EQUIPMENT.value,
                "comments": f"Derived: {location_config.harness_fraction}% of "
                f"{base_kg:.3f} kg equipment mass",
                "eqpt_total_mass": harness_kg,
            }
        )

    return pd.DataFrame(records, columns=list(_FRAME_COLUMNS))
