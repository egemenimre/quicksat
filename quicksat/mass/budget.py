# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Mass budget assembly and reporting.

"""

import os
from pathlib import Path
from typing import cast

import pandas as pd
import yaml
from pandas.io.formats.style import Styler
from pydantic import BaseModel, Field, ValidationError

from quicksat import Q_
from quicksat.mass.equipment import Equipment, MassClass
from quicksat.mass.report import tabulate

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


class LocationConfig(BaseModel):
    """Margin and harness settings for a single location."""

    system_margin: float = Field(default=0.0, ge=0)
    """System margin for this location, as a percentage, applied to its subtotal."""

    harness_fraction: float = Field(default=0.0, ge=0)
    """Harness mass as a percentage of this location's equipment mass, before margin."""

    harness_margin: float = Field(default=0.0, ge=0)
    """Contingency on the derived harness mass, as a percentage."""

    retained_in_orbit: bool = True
    """Whether hardware here survives separation."""


_LAUNCHER_DEFAULT = LocationConfig(retained_in_orbit=False)


class MassBudgetConfig(BaseModel):
    """
    Budget settings, keyed on location.

    Location is the single computation axis. It holds both the system margin and the
    harness parameters. So it is always clear which margin applies to a derived harness
    row.
    """

    locations: dict[str, LocationConfig] = Field(default_factory=dict)

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "MassBudgetConfig":
        """
        Initialise the budget config from a YAML file.

        Parameters
        ----------
        file_path : str | Path
            Filepath containing the config data (YAML)

        Returns
        -------
        config : MassBudgetConfig
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
    def from_yaml_text(cls, yaml_text: str) -> "MassBudgetConfig":
        """
        Initialise the budget config from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the config data (YAML)

        Returns
        -------
        config : MassBudgetConfig
            Config object from the input data
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        return cls(**yaml.safe_load(yaml_text))

    def for_location(self, name: str) -> LocationConfig:
        """
        Settings for a location.

        `Launcher` is reserved and needs no entry. It defaults to no margins, no
        harness, and being left behind at separation. Any other unlisted location raises
        an error. Treating it as zero would make the budget too low, with no warning.

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

    The budget is a table, not a hierarchy. Location, responsibility and subsystem are
    independent axes. An item can sit on the platform and still be the payload team's
    responsibility. So a tree would have to make one of the three its main structure,
    with side tables for the others. `groupby` gives all three views with no extra code.

    Every query takes the same four flags. By default, they describe the satellite as it
    flies at the start of life. So the usual query needs no arguments, and each change
    from it is one explicit flag:

    propellant
        Percentage of the propellant load to count: 100 at the start of life, 0 at
        the end, and anything between for a point part-way through the mission.
    sys_margin
        Apply the location's system margin.
    eqpt_margin
        Apply the per-item equipment margin.
    in_orbit
        Drop hardware at locations that do not survive separation.

    Parameters
    ----------
    equipment : list[Equipment]
        Validated equipment items
    config : MassBudgetConfig
        Margin and harness settings, keyed on location
    """

    def __init__(self, equipment: list[Equipment], config: MassBudgetConfig):
        """
        Assembles the budget, validating locations and deriving the harness rows.

        Parameters
        ----------
        equipment : list[Equipment]
            Validated equipment items
        config : MassBudgetConfig
            Margin and harness settings, keyed on location
        """
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
        Build a mass budget from an equipment CSV and a config YAML.

        Parameters
        ----------
        csv_path : str | Path
            Filepath of the equipment list (CSV)
        config_path : str | Path
            Filepath of the budget config (YAML)

        Returns
        -------
        budget : MassBudget
            The assembled budget
        """
        config = MassBudgetConfig.from_yaml_file(Path(config_path))
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
    def eqpt_table(self) -> pd.DataFrame:
        """
        The validated equipment table, harness rows included.

        Returns
        -------
        frame : pd.DataFrame
            A copy of the working table, one row per item
        """
        return self._frame.copy()

    def resolve(
        self,
        propellant: float = 100.0,
        in_orbit: bool = True,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
    ) -> pd.DataFrame:
        """
        The equipment table for one case, with a `mass` column per the flags.

        Every factor is per row and linear. So the location retention, the margins and
        the harness rows combine without affecting each other.

        Parameters
        ----------
        propellant : float
            Percentage of the propellant load to count
        in_orbit : bool
            Drop hardware at locations that do not survive separation
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin

        Returns
        -------
        frame : pd.DataFrame
            Retained rows, with a `mass` column added
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
        Total mass. The general query that the others call with a filter.

        Parameters
        ----------
        propellant : float
            Percentage of the propellant load to count
        in_orbit : bool
            Drop hardware at locations that do not survive separation
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin


        Returns
        -------
        mass : Quantity
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
        Mass after separation, excluding hardware left with the launcher.

        Parameters
        ----------
        propellant : float
            Percentage of the propellant load to count
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin

        Returns
        -------
        mass : Quantity
            The in-orbit mass
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
        Mass before separation, including the launcher-side hardware.

        Parameters
        ----------
        propellant : float
            Percentage of the propellant load to count
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin

        Returns
        -------
        mass : Quantity
            The on-ground mass
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
        Platform mass, summed on location or on responsibility.

        It takes no `in_orbit` flag. Retention is a property of the location, and the
        platform is retained, so the flag could not change the answer.

        Parameters
        ----------
        propellant : float
            Percentage of the propellant load to count
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin
        by_responsibility : bool
            Sum rows whose `responsibility` is Platform. Otherwise, sum by `location`

        Returns
        -------
        mass : Quantity
            The platform mass
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
        Payload mass, summed on location or on responsibility.

        Parameters
        ----------
        propellant : float
            Percentage of the propellant load to count
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin
        by_responsibility : bool
            Sum rows whose `responsibility` is Payload. Otherwise, sum by `location`

        Returns
        -------
        mass : Quantity
            The payload mass
        """
        return self._named_mass(
            PAYLOAD_LOCATION, propellant, sys_margin, eqpt_margin, by_responsibility
        )

    def subsystem_mass(self, subsys_id: str, eqpt_margin: bool = True):
        """
        Mass of one subsystem.

        It includes no system margin. System margins are held at the platform and
        payload level, and cannot be assigned to a subsystem. It needs no `propellant`
        flag either. A propellant row has its own `subsystem`. So a Propulsion query
        includes the propellant, and no other subsystem is affected.

        Parameters
        ----------
        subsys_id : str
            Subsystem name, as it appears in the equipment file
        eqpt_margin : bool
            Apply the per-item equipment margin

        Returns
        -------
        mass : Quantity
            The subsystem mass, at the full propellant load
        """
        frame = self.resolve(
            propellant=100.0, in_orbit=True, sys_margin=False, eqpt_margin=eqpt_margin
        )
        return Q_(frame.loc[frame["subsystem"] == subsys_id, "mass"].sum(), "kg")

    def propellant_mass(self):
        """
        Propellant mass, with no margin.

        It takes no flags. Propellant never takes a margin, and it is present both on
        the ground and in orbit.

        Returns
        -------
        mass : Quantity
            The full propellant load
        """
        frame = self._frame
        is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
        return Q_(frame.loc[is_propellant, "eqpt_total_mass"].sum(), "kg")

    def by_location(self, **kwargs) -> pd.DataFrame:
        """
        Mass grouped by location.

        Parameters
        ----------
        **kwargs
            The query flags, passed through to `resolve`

        Returns
        -------
        grouped : pd.DataFrame
            One row per location, with a single `mass` column
        """
        return self._grouped("location", **kwargs)

    def by_responsibility(self, **kwargs) -> pd.DataFrame:
        """
        Mass grouped by responsibility.

        Parameters
        ----------
        **kwargs
            The query flags, passed through to `resolve`

        Returns
        -------
        grouped : pd.DataFrame
            One row per responsibility, with a single `mass` column
        """
        return self._grouped("responsibility", **kwargs)

    def by_subsystem(self, **kwargs) -> pd.DataFrame:
        """
        Mass grouped by subsystem.

        Parameters
        ----------
        **kwargs
            The query flags, passed through to `resolve`

        Returns
        -------
        grouped : pd.DataFrame
            One row per subsystem, with a single `mass` column
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

        Equipment is grouped by subsystem within each location. Each location then gets
        its subtotal before system margin, the margin itself, and its total after
        margin. The dry mass, the propellant and the wet mass follow the location
        totals.

        Propellant appears once, at the bottom, and is left out of the blocks above it.
        So every subtotal above it is a dry mass, and the column adds up in reading
        order. So `subsystem_mass("Propulsion")` is wet, while the Propulsion subtotal
        here is dry. They answer different questions.

        Parameters
        ----------
        in_orbit : bool
            When set, launcher-side hardware is left out, and the totals are the
            in-orbit masses. Otherwise, a launcher block joins the others, and the
            totals become the on-ground masses.
        subsystem_subtotals : bool
            Add a subtotal line after each subsystem block. Off by default, because on a
            table this size the extra lines hide the items. The blocks stay grouped by
            subsystem either way.
        comments : bool
            Show the equipment file's `comments` column. Off by default, because free
            text makes the table wide. The derived harness rows say there how they were
            derived. The column is in `.data` either way.

        Returns
        -------
        report : Styler
            One row per item and per subtotal. A Styler rather than a plain frame, so
            that cells which do not apply to a row are blank instead of NaN. The frame
            is still there as `.data`, where every row also has the `row_type` that the
            displayed table hides.
        """
        return tabulate(
            self._frame, self.config, in_orbit, subsystem_subtotals, comments
        )

    def _named_mass(self, name, propellant, sys_margin, eqpt_margin, by_responsibility):
        """
        Sums one location's or one responsibility's rows.

        Parameters
        ----------
        name : str
            The location or responsibility to match
        propellant : float
            Percentage of the propellant load to count
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin
        by_responsibility : bool
            Match on `responsibility` rather than `location`

        Returns
        -------
        mass : Quantity
            The matching rows' mass
        """
        frame = self.resolve(
            propellant=propellant,
            in_orbit=True,
            sys_margin=sys_margin,
            eqpt_margin=eqpt_margin,
        )
        column = "responsibility" if by_responsibility else "location"
        return Q_(frame.loc[frame[column] == name, "mass"].sum(), "kg")

    def _grouped(self, column: str, **kwargs) -> pd.DataFrame:
        """
        Sums the resolved mass over one grouping axis.

        Parameters
        ----------
        column : str
            The column to group on
        **kwargs
            The query flags, passed through to `resolve`

        Returns
        -------
        grouped : pd.DataFrame
            One row per distinct value, with a single `mass` column
        """
        frame = self.resolve(**kwargs)
        return cast(pd.DataFrame, frame.groupby(column, sort=True)[["mass"]].sum())

    def _mass(
        self,
        frame: pd.DataFrame,
        sys_margin: bool,
        eqpt_margin: bool,
        propellant: float,
    ):
        """
        Mass per row for a flag combination.

        The figure is built from the flags, rather than chosen from three precomputed
        columns. This covers every combination in the same way, including a system
        margin without the equipment margin.

        Parameters
        ----------
        frame : pd.DataFrame
            The rows to weigh, already filtered for the case
        sys_margin : bool
            Apply the location's system margin
        eqpt_margin : bool
            Apply the per-item equipment margin
        propellant : float
            Percentage of the propellant load to count

        Returns
        -------
        mass : pd.Series
            Mass per row, aligned with `frame`
        """
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
    """
    Flattens validated equipment into the working table, in kg.

    Parameters
    ----------
    equipment : list[Equipment]
        Validated equipment items

    Returns
    -------
    frame : pd.DataFrame
        One row per item, with the mass columns as plain floats
    """
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
    """
    Rejects a repeated equipment id within one location.

    The same id may appear at several locations, because separate items often share a
    name. But it may not appear twice in the same place.

    Parameters
    ----------
    frame : pd.DataFrame
        The equipment table to check

    Raises
    ------
    ValueError
        If any (equipment_id, location) pair appears more than once
    """
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
    Derives one harness row per location.

    The base is the equipment mass at that location, before margin. Propellant is left
    out, because cabling scales with the boxes it connects. The mass before margin is
    used, so that the harness estimate does not compound the equipment margins.

    The row takes its location's name as its responsibility, so that a sum over either
    axis includes it. A location may hold items of several responsibilities. The whole
    harness then goes to the location's own name.

    Parameters
    ----------
    frame : pd.DataFrame
        The equipment table, before harness rows are added
    config : MassBudgetConfig
        Margin and harness settings, keyed on location

    Returns
    -------
    harness : pd.DataFrame
        One row per location with a non-zero harness fraction
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
