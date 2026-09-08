# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Mass budget assembly and reporting.

"""

import os
from enum import Enum
from pathlib import Path

import pandas as pd
import yaml
from pydantic import BaseModel, Field, ValidationError

from quicksat import Q_
from quicksat.mass.equipment import Equipment, MassClass

LAUNCHER_LOCATION = "Launcher"
"""Reserved location name for hardware that stays with the launch vehicle."""

HARNESS_SUBSYSTEM = "Harness"
"""Subsystem and responsibility tag given to the derived harness rows."""

REQUIRED_COLUMNS = (
    "equipment_id",
    "equipment_name",
    "location",
    "responsibility",
    "subsystem",
    "unit_mass",
    "equipment_margin",
    "number_of_units",
)

_FRAME_COLUMNS = (
    "equipment_id",
    "equipment_name",
    "location",
    "responsibility",
    "subsystem",
    "unit_mass_kg",
    "equipment_margin",
    "number_of_units",
    "mass_class",
    "comments",
    "cbe_kg",
)


class MassCase(str, Enum):
    """Which point in the mission the budget is reported for."""

    ON_GROUND = "on_ground"
    """Before separation. Everything is counted, launcher-side hardware included."""

    IN_ORBIT = "in_orbit"
    """After separation. Hardware at non-retained locations is dropped."""


class LocationConfig(BaseModel):
    """Margin and harness settings for a single location."""

    system_margin: float = Field(default=0.0, ge=0)
    """System margin for this location, as a percentage, applied to its subtotal."""

    harness_fraction: float = Field(default=0.0, ge=0)
    """Harness mass as a percentage of this location's equipment CBE."""

    harness_margin: float = Field(default=0.0, ge=0)
    """Contingency on the derived harness mass, as a percentage."""

    retained_in_orbit: bool = True
    """Whether hardware here survives separation."""


_LAUNCHER_DEFAULT = LocationConfig(retained_in_orbit=False)


class BudgetConfig(BaseModel):
    """
    Budget settings, keyed on location.

    Location is the single computation axis: it carries both the system margin and
    the harness parameters, so the derived harness rows are never ambiguous about
    which margin applies to them.
    """

    locations: dict[str, LocationConfig] = Field(default_factory=dict)

    @classmethod
    def from_yaml_file(cls, file_path: Path) -> "BudgetConfig":
        """
        Initialise the budget config from a YAML file.

        Parameters
        ----------
        file_path : Path
            Filepath containing the config data (YAML)

        Returns
        -------
        config : BudgetConfig
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
    def from_yaml_text(cls, yaml_text: str) -> "BudgetConfig":
        """
        Initialise the budget config from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the config data (YAML)

        Returns
        -------
        config : BudgetConfig
            Config object from the input data
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        return cls(**yaml.safe_load(yaml_text))

    def for_location(self, name: str) -> LocationConfig:
        """
        Settings for a location.

        `Launcher` is reserved and needs no entry: it defaults to no margins, no
        harness, and being dropped at separation. Any other unlisted location is an
        error rather than a silent zero, which would quietly understate the budget.

        Parameters
        ----------
        name : str
            Location name

        Returns
        -------
        location_config : LocationConfig
            Settings for that location
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
    A satellite mass budget assembled from a flat equipment list.

    The budget is a table, not a hierarchy. Location, responsibility and subsystem
    are cross-cutting axes — an item can sit on the platform while being the payload
    team's responsibility — so any tree would have to privilege one of the three and
    express the others as side tables. `groupby` gives all three for free.

    Parameters
    ----------
    equipment : list[Equipment]
        Validated equipment items
    config : BudgetConfig
        Margin and harness settings, keyed on location
    """

    def __init__(self, equipment: list[Equipment], config: BudgetConfig):
        self.config = config
        frame = _frame_from_items(equipment)
        _check_duplicates(frame)
        for location in frame["location"].unique():
            config.for_location(location)
        self._frame = pd.concat(
            [frame, _harness_frame(frame, config)], ignore_index=True
        )

    @classmethod
    def from_csv(cls, csv_path: Path, config_path: Path) -> "MassBudget":
        """
        Build a mass budget from an equipment CSV and a config YAML.

        Parameters
        ----------
        csv_path : Path
            Filepath of the equipment list (CSV)
        config_path : Path
            Filepath of the budget config (YAML)

        Returns
        -------
        budget : MassBudget
            The assembled budget
        """
        config = BudgetConfig.from_yaml_file(Path(config_path))
        raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False)

        missing = [name for name in REQUIRED_COLUMNS if name not in raw.columns]
        if missing:
            raise ValueError(f"{csv_path}: missing columns {missing}")

        equipment = []
        for row_number, record in enumerate(raw.to_dict("records"), start=2):
            try:
                equipment.append(Equipment(**record))
            except ValidationError as exc:
                raise ValueError(f"{csv_path}, row {row_number}:\n{exc}") from exc

        return cls(equipment, config)

    @property
    def equipment(self) -> pd.DataFrame:
        """The validated equipment table, harness rows included."""
        return self._frame.copy()

    def resolve(
        self,
        case: MassCase = MassCase.IN_ORBIT,
        with_propellant: bool = True,
    ) -> pd.DataFrame:
        """
        The equipment table for one mass case, with the margins applied per row.

        Every factor is per row and linear, so the location retention, the margins
        and the harness rows compose without interfering.

        Parameters
        ----------
        case : MassCase
            Mission point to report for
        with_propellant : bool
            Whether propellant is counted

        Returns
        -------
        frame : pd.DataFrame
            Retained rows, with `mev_kg` and `total_kg` columns added
        """
        frame = self._frame
        is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value

        if not with_propellant:
            frame = frame[~is_propellant]
        if case is MassCase.IN_ORBIT:
            retained = frame["location"].map(
                lambda name: self.config.for_location(name).retained_in_orbit
            )
            frame = frame[retained]

        is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
        system_factor = frame["location"].map(
            lambda name: 1.0 + self.config.for_location(name).system_margin / 100.0
        )
        mev = frame["cbe_kg"] * (1.0 + frame["equipment_margin"] / 100.0)
        total = mev * system_factor

        # propellant carries no margins at all, so it also sits outside the
        # system margin rather than only skipping the equipment margin
        return frame.assign(
            mev_kg=mev.mask(is_propellant, frame["cbe_kg"]),
            total_kg=total.mask(is_propellant, frame["cbe_kg"]),
        )

    def total(
        self,
        case: MassCase = MassCase.IN_ORBIT,
        with_propellant: bool = True,
    ):
        """
        Total mass for one case.

        Parameters
        ----------
        case : MassCase
            Mission point to report for
        with_propellant : bool
            Whether propellant is counted

        Returns
        -------
        total : Quantity
            The case mass
        """
        return Q_(self.resolve(case, with_propellant)["total_kg"].sum(), "kg")

    def by_location(self, **kwargs) -> pd.DataFrame:
        """Totals grouped by location. Takes the same arguments as `resolve`."""
        return self._grouped("location", **kwargs)

    def by_responsibility(self, **kwargs) -> pd.DataFrame:
        """Totals grouped by responsibility. Takes the same arguments as `resolve`."""
        return self._grouped("responsibility", **kwargs)

    def by_subsystem(self, **kwargs) -> pd.DataFrame:
        """Totals grouped by subsystem. Takes the same arguments as `resolve`."""
        return self._grouped("subsystem", **kwargs)

    def _grouped(self, column: str, **kwargs) -> pd.DataFrame:
        """Sums CBE, MEV and total mass over one grouping axis."""
        frame = self.resolve(**kwargs)
        grouped = frame.groupby(column, sort=True)[
            ["cbe_kg", "mev_kg", "total_kg"]
        ].sum()
        return grouped.rename(
            columns={"cbe_kg": "cbe", "mev_kg": "mev", "total_kg": "total"}
        )


def _frame_from_items(equipment: list[Equipment]) -> pd.DataFrame:
    """Flattens validated equipment into the working table, in canonical kg."""
    records = []
    for item in equipment:
        unit_mass_kg = item.unit_mass.to("kg").magnitude
        records.append(
            {
                "equipment_id": item.equipment_id,
                "equipment_name": item.equipment_name,
                "location": item.location,
                "responsibility": item.responsibility,
                "subsystem": item.subsystem,
                "unit_mass_kg": unit_mass_kg,
                "equipment_margin": item.equipment_margin,
                "number_of_units": item.number_of_units,
                "mass_class": item.mass_class.value,
                "comments": item.comments,
                "cbe_kg": unit_mass_kg * item.number_of_units,
            }
        )

    frame = pd.DataFrame(records, columns=list(_FRAME_COLUMNS))
    for column in ("unit_mass_kg", "equipment_margin", "cbe_kg"):
        frame[column] = frame[column].astype(float)
    frame["number_of_units"] = frame["number_of_units"].astype(int)
    return frame


def _check_duplicates(frame: pd.DataFrame) -> None:
    """Rejects a repeated equipment id within one location."""
    duplicated = frame.duplicated(subset=["equipment_id", "location"], keep=False)
    if duplicated.any():
        pairs = (
            frame.loc[duplicated, ["equipment_id", "location"]]
            .drop_duplicates()
            .to_dict("records")
        )
        raise ValueError(f"Duplicate (equipment_id, location) pairs: {pairs}")


def _harness_frame(frame: pd.DataFrame, config: BudgetConfig) -> pd.DataFrame:
    """
    Derives one harness row per location.

    The base is the equipment CBE at that location: propellant is excluded because
    cabling scales with the boxes it connects, and CBE is used rather than margined
    mass so the harness estimate does not compound the equipment margins.
    """
    hardware = frame[frame["mass_class"] == MassClass.EQUIPMENT.value]
    records = []

    for location, group in hardware.groupby("location", sort=True):
        location_config = config.for_location(location)
        base_kg = group["cbe_kg"].sum()
        harness_kg = base_kg * location_config.harness_fraction / 100.0
        if harness_kg <= 0:
            continue
        records.append(
            {
                "equipment_id": f"harness_{location.lower()}",
                "equipment_name": f"{location} harness",
                "location": location,
                "responsibility": HARNESS_SUBSYSTEM,
                "subsystem": HARNESS_SUBSYSTEM,
                "unit_mass_kg": harness_kg,
                "equipment_margin": location_config.harness_margin,
                "number_of_units": 1,
                "mass_class": MassClass.EQUIPMENT.value,
                "comments": f"Derived: {location_config.harness_fraction}% of "
                f"{base_kg:.3f} kg equipment CBE",
                "cbe_kg": harness_kg,
            }
        )

    return pd.DataFrame(records, columns=list(_FRAME_COLUMNS))
