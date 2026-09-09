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

import pandas as pd
import yaml
from pydantic import BaseModel, Field, ValidationError

from quicksat import Q_
from quicksat.mass.equipment import Equipment, MassClass

LAUNCHER_LOCATION = "Launcher"
"""Reserved location name for hardware that stays with the launch vehicle."""

PLATFORM_LOCATION = "Platform"
"""Conventional name for the satellite bus, used by `MassBudget.platform_mass`."""

PAYLOAD_LOCATION = "Payload"
"""Conventional name for the payload, used by `MassBudget.payload_mass`."""

HARNESS_SUBSYSTEM = "Harness"
"""Subsystem tag given to the derived harness rows."""

NAN = float("nan")

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
    "eqpt_mass",
    "equipment_margin",
    "number_of_units",
    "mass_class",
    "comments",
    "eqpt_total_mass",
)

_REPORT_COLUMNS = (
    "label",
    "equipment_name",
    "location",
    "subsystem",
    "units",
    "eqpt_mass",
    "margin_pct",
    "eqpt_total_mass",
    "eqpt_total_mass_with_margin",
    "total_mass_with_sys_margin",
    "row_type",
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

    Every query takes the same four flags, all defaulting to `True`, so the common
    question is a bare call and each deviation is one explicit switch:

    wet
        Count propellant.
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
        wet: bool = True,
        in_orbit: bool = True,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
    ) -> pd.DataFrame:
        """
        The equipment table for one case, with a `mass` column per the flags.

        Every factor is per row and linear, so the location retention, the margins
        and the harness rows compose without interfering.

        Parameters
        ----------
        wet : bool
            Count propellant
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
        frame = self._frame

        if not wet:
            frame = frame[frame["mass_class"] != MassClass.PROPELLANT.value]
        if in_orbit:
            retained = frame["location"].map(
                lambda name: self.config.for_location(name).retained_in_orbit
            )
            frame = frame[retained]

        return frame.assign(mass=self._mass(frame, sys_margin, eqpt_margin))

    def total_mass(
        self,
        wet: bool = True,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
        in_orbit: bool = True,
    ):
        """
        Total mass. The generic query the others are presets of.

        Returns
        -------
        mass : Quantity
        """
        frame = self.resolve(
            wet=wet, in_orbit=in_orbit, sys_margin=sys_margin, eqpt_margin=eqpt_margin
        )
        return Q_(frame["mass"].sum(), "kg")

    def in_orbit_mass(
        self, wet: bool = True, sys_margin: bool = True, eqpt_margin: bool = True
    ):
        """Mass after separation, excluding hardware left with the launcher."""
        return self.total_mass(
            wet=wet, sys_margin=sys_margin, eqpt_margin=eqpt_margin, in_orbit=True
        )

    def on_ground_mass(
        self, wet: bool = True, sys_margin: bool = True, eqpt_margin: bool = True
    ):
        """Mass before separation, including the launcher-side hardware."""
        return self.total_mass(
            wet=wet, sys_margin=sys_margin, eqpt_margin=eqpt_margin, in_orbit=False
        )

    def platform_mass(
        self,
        wet: bool = True,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
        by_location: bool = True,
    ):
        """
        Platform mass, summed on location or on responsibility.

        Takes no `in_orbit` flag: retention is a property of the location, and the
        platform is retained, so the flag could not change the answer.

        Parameters
        ----------
        by_location : bool
            Sum rows whose `location` is Platform; otherwise their `responsibility`
        """
        return self._named_mass(
            PLATFORM_LOCATION, wet, sys_margin, eqpt_margin, by_location
        )

    def payload_mass(
        self,
        wet: bool = True,
        sys_margin: bool = True,
        eqpt_margin: bool = True,
        by_location: bool = True,
    ):
        """
        Payload mass, summed on location or on responsibility.

        Parameters
        ----------
        by_location : bool
            Sum rows whose `location` is Payload; otherwise their `responsibility`
        """
        return self._named_mass(
            PAYLOAD_LOCATION, wet, sys_margin, eqpt_margin, by_location
        )

    def subsystem_mass(self, subsys_id: str, eqpt_margin: bool = True):
        """
        Mass of one subsystem.

        Carries no system margin: system margins are held at the platform and
        payload level and cannot be attributed to a subsystem. Nor does it need a
        `wet` flag — a propellant row carries its own `subsystem`, so a propulsion
        query picks the propellant up and every other subsystem is unaffected.

        Parameters
        ----------
        subsys_id : str
            Subsystem name, as it appears in the equipment file
        eqpt_margin : bool
            Apply the per-item equipment margin
        """
        frame = self.resolve(
            wet=True, in_orbit=True, sys_margin=False, eqpt_margin=eqpt_margin
        )
        return Q_(frame.loc[frame["subsystem"] == subsys_id, "mass"].sum(), "kg")

    def propellant_mass(self):
        """
        Propellant mass, at face value.

        Takes no flags: propellant is never margined, and it is present both on the
        ground and in orbit.
        """
        frame = self._frame
        is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
        return Q_(frame.loc[is_propellant, "eqpt_total_mass"].sum(), "kg")

    def by_location(self, **kwargs) -> pd.DataFrame:
        """Mass grouped by location. Takes the same flags as `total_mass`."""
        return self._grouped("location", **kwargs)

    def by_responsibility(self, **kwargs) -> pd.DataFrame:
        """Mass grouped by responsibility. Takes the same flags as `total_mass`."""
        return self._grouped("responsibility", **kwargs)

    def by_subsystem(self, **kwargs) -> pd.DataFrame:
        """Mass grouped by subsystem. Takes the same flags as `total_mass`."""
        return self._grouped("subsystem", **kwargs)

    def tabulated_mass(self, in_orbit: bool = True) -> pd.DataFrame:
        """
        The budget as a document: every item, with subtotals in reading order.

        Equipment is grouped into subsystem blocks within each location, each block
        subtotalled, then the location subtotal before its system margin, the margin
        itself, and the location total after it. The location totals are followed by
        the dry mass, the propellant, and the wet mass.

        Propellant appears once, at the bottom, and is left out of the blocks above
        it, so every subtotal on the way down is a dry mass and the column adds up as
        it reads. `subsystem_mass("Propulsion")` is therefore wet where the
        propulsion subtotal here is dry — they answer different questions.

        Parameters
        ----------
        in_orbit : bool
            When set, launcher-side hardware is absent and the totals are the
            in-orbit masses; otherwise a launcher block joins the others and the
            totals become the on-ground masses.

        Returns
        -------
        report : pd.DataFrame
            One row per item and per subtotal, tagged by `row_type`
        """
        return _tabulate(self, in_orbit)

    def _named_mass(self, name, wet, sys_margin, eqpt_margin, by_location):
        """Sums one location's or one responsibility's rows."""
        frame = self.resolve(
            wet=wet, in_orbit=True, sys_margin=sys_margin, eqpt_margin=eqpt_margin
        )
        column = "location" if by_location else "responsibility"
        return Q_(frame.loc[frame[column] == name, "mass"].sum(), "kg")

    def _grouped(self, column: str, **kwargs) -> pd.DataFrame:
        """Sums the resolved mass over one grouping axis."""
        frame = self.resolve(**kwargs)
        grouped = frame.groupby(column, sort=True)[["mass"]].sum()
        return grouped.rename(columns={"mass": "mass"})

    def _mass(self, frame: pd.DataFrame, sys_margin: bool, eqpt_margin: bool):
        """
        Mass per row for a flag combination.

        Building the figure from the flags rather than selecting one of three
        precomputed columns covers every combination uniformly, including margining
        by system but not by equipment.
        """
        mass = frame["eqpt_total_mass"]
        if eqpt_margin:
            mass = mass * (1.0 + frame["equipment_margin"] / 100.0)
        if sys_margin:
            mass = mass * frame["location"].map(
                lambda name: 1.0 + self.config.for_location(name).system_margin / 100.0
            )
        # propellant is never margined, whatever the flags say
        is_propellant = frame["mass_class"] == MassClass.PROPELLANT.value
        return mass.mask(is_propellant, frame["eqpt_total_mass"])


def _frame_from_items(equipment: list[Equipment]) -> pd.DataFrame:
    """Flattens validated equipment into the working table, in canonical kg."""
    records = []
    for item in equipment:
        eqpt_mass = item.unit_mass.to("kg").magnitude
        records.append(
            {
                "equipment_id": item.equipment_id,
                "equipment_name": item.equipment_name,
                "location": item.location,
                "responsibility": item.responsibility,
                "subsystem": item.subsystem,
                "eqpt_mass": eqpt_mass,
                "equipment_margin": item.equipment_margin,
                "number_of_units": item.number_of_units,
                "mass_class": item.mass_class.value,
                "comments": item.comments,
                "eqpt_total_mass": eqpt_mass * item.number_of_units,
            }
        )

    frame = pd.DataFrame(records, columns=list(_FRAME_COLUMNS))
    for column in ("eqpt_mass", "equipment_margin", "eqpt_total_mass"):
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

    The base is the equipment mass at that location before margin: propellant is
    excluded because cabling scales with the boxes it connects, and the unmargined
    mass is used so the harness estimate does not compound the equipment margins.

    The row takes its location's name as its responsibility, so that summing on
    either axis includes it. Where a location hosts several responsibilities, that
    attributes the whole harness to the location's own name.
    """
    hardware = frame[frame["mass_class"] == MassClass.EQUIPMENT.value]
    records = []

    for location, group in hardware.groupby("location", sort=True):
        location_config = config.for_location(location)
        base_kg = group["eqpt_total_mass"].sum()
        harness_kg = base_kg * location_config.harness_fraction / 100.0
        if harness_kg <= 0:
            continue
        records.append(
            {
                "equipment_id": f"harness_{location.lower()}",
                "equipment_name": f"{location} harness",
                "location": location,
                "responsibility": location,
                "subsystem": HARNESS_SUBSYSTEM,
                "eqpt_mass": harness_kg,
                "equipment_margin": location_config.harness_margin,
                "number_of_units": 1,
                "mass_class": MassClass.EQUIPMENT.value,
                "comments": f"Derived: {location_config.harness_fraction}% of "
                f"{base_kg:.3f} kg equipment mass",
                "eqpt_total_mass": harness_kg,
            }
        )

    return pd.DataFrame(records, columns=list(_FRAME_COLUMNS))


def _report_row(label: str, row_type: str, **values) -> dict:
    """One row of the tabulated report, with everything not supplied left blank."""
    row = dict.fromkeys(_REPORT_COLUMNS, NAN)
    row.update(equipment_name="", location="", subsystem="")
    row.update(label=label, row_type=row_type)
    row.update(values)
    return row


def _tabulate(budget: "MassBudget", in_orbit: bool) -> pd.DataFrame:
    """
    Assembles the mass budget document.

    Locations and subsystems come out in order of first appearance in the equipment
    file rather than sorted, so the report keeps the structure the file was written
    with — and the derived harness, appended last, lands at the foot of its location.
    """
    hardware = budget._frame[budget._frame["mass_class"] != MassClass.PROPELLANT.value]
    if in_orbit:
        retained = hardware["location"].map(
            lambda name: budget.config.for_location(name).retained_in_orbit
        )
        hardware = hardware[retained]

    rows = []
    totals = []

    for location in hardware["location"].drop_duplicates():
        block = hardware[hardware["location"] == location]

        for subsystem in block["subsystem"].drop_duplicates():
            items = block[block["subsystem"] == subsystem]
            item_margined = _with_margin(items)
            for item in items.itertuples():
                rows.append(
                    _report_row(
                        item.equipment_id,
                        "equipment",
                        equipment_name=item.equipment_name,
                        location=location,
                        subsystem=subsystem,
                        units=item.number_of_units,
                        eqpt_mass=item.eqpt_mass,
                        margin_pct=item.equipment_margin,
                        eqpt_total_mass=item.eqpt_total_mass,
                        eqpt_total_mass_with_margin=item_margined.loc[item.Index],
                    )
                )
            rows.append(
                _report_row(
                    f"{subsystem} subtotal",
                    "subsystem_subtotal",
                    location=location,
                    subsystem=subsystem,
                    eqpt_total_mass=items["eqpt_total_mass"].sum(),
                    eqpt_total_mass_with_margin=item_margined.sum(),
                )
            )

        block_raw = block["eqpt_total_mass"].sum()
        block_margined = _with_margin(block).sum()
        margin_pct = budget.config.for_location(location).system_margin
        margin_kg = block_margined * margin_pct / 100.0

        rows.append(
            _report_row(
                f"{location} subtotal (before system margin)",
                "location_subtotal",
                location=location,
                eqpt_total_mass=block_raw,
                eqpt_total_mass_with_margin=block_margined,
            )
        )
        rows.append(
            _report_row(
                f"{location} system margin ({margin_pct:g}%)",
                "system_margin",
                location=location,
                margin_pct=margin_pct,
                total_mass_with_sys_margin=margin_kg,
            )
        )
        rows.append(
            _report_row(
                f"{location} total",
                "location_total",
                location=location,
                eqpt_total_mass=block_raw,
                eqpt_total_mass_with_margin=block_margined,
                total_mass_with_sys_margin=block_margined + margin_kg,
            )
        )
        totals.append((block_raw, block_margined, block_margined + margin_kg))

    dry_raw = sum(entry[0] for entry in totals)
    dry_margined = sum(entry[1] for entry in totals)
    dry_total = sum(entry[2] for entry in totals)
    propellant_kg = budget.propellant_mass().to("kg").magnitude

    rows.append(
        _report_row(
            "Total Dry Mass (with system margin)",
            "dry_total",
            eqpt_total_mass=dry_raw,
            eqpt_total_mass_with_margin=dry_margined,
            total_mass_with_sys_margin=dry_total,
        )
    )
    rows.append(
        _report_row(
            "Propellant",
            "propellant",
            eqpt_total_mass=propellant_kg,
            total_mass_with_sys_margin=propellant_kg,
        )
    )
    rows.append(
        _report_row(
            "Total Wet Mass",
            "wet_total",
            eqpt_total_mass=dry_raw + propellant_kg,
            eqpt_total_mass_with_margin=dry_margined + propellant_kg,
            total_mass_with_sys_margin=dry_total + propellant_kg,
        )
    )

    return pd.DataFrame(rows, columns=list(_REPORT_COLUMNS))


def _with_margin(frame: pd.DataFrame) -> pd.Series:
    """Margined mass per row, for the hardware rows of the report."""
    return frame["eqpt_total_mass"] * (1.0 + frame["equipment_margin"] / 100.0)
