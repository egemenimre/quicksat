# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power consumption files, and the loads they give over a scenario run.

There are two files, `payload_consumption.csv` and `platform_consumption.csv`, one for
each group. Each row is a piece of equipment, with its power in each of its group's
modes. Every mode the run gives a group needs its column, the platform's `slew`
included. The energy comes from the mode intervals, not the grid.
`docs/power/power_consumption_ref.ipynb` explains the files.

"""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import pandas as pd
from astropy.units import Quantity
from pydantic import BaseModel, ConfigDict, Field

from quicksat import Q_, u
from quicksat.power.orbits import interval_pieces, whole_orbits
from quicksat.scenario.names import GROUPS, PLATFORM
from quicksat.scenario.run import ScenarioRun
from quicksat.utils.intervals import labels_at
from quicksat.utils.parser_helpers import (
    NoSpaceStr,
    PowerQty,
    read_csv_rows,
    validated_rows,
)

REQUIRED_COLUMNS = (
    "equipment_id",
    "equipment_name",
    "subsystem",
    "units_on",
    "eqpt_margin",
)
"""The columns every consumption file needs, before the modes."""

THERMAL_COLUMN = "thermal"
"""The column that says where a payload row's heat goes."""

INSIDE_MLI = "inside_mli"
"""A row whose power is all dissipated inside the payload's MLI."""

OUTSIDE_MLI = "outside_mli"
"""A row whose power is dissipated outside the payload's MLI, out of its thermal
account."""

HEATER = "heater"
"""The row of all the payload's heater lines, dissipated inside the MLI."""

THERMAL_VALUES = (INSIDE_MLI, OUTSIDE_MLI, HEATER)
"""The values of the `thermal` column."""

OPTIONAL_COLUMNS = ("comments", THERMAL_COLUMN)
"""Columns that may be there, and are not modes."""


class Load(BaseModel):
    """
    One row of a consumption file: a piece of equipment and its power by mode, checked
    as it is read.

    Parameters
    ----------
    equipment_id : str
        A short name, with no spaces, such as `star_tracker`
    equipment_name : str
        Its full name
    subsystem : str
        Its subsystem, with no spaces, such as `ADCS`
    units_on : int
        The units that draw power, 0 for none
    eqpt_margin : float
        The equipment margin, in percent
    power : dict of str to Quantity
        One unit's power in each mode, by name
    comments : str, optional
        Free text notes
    thermal : str, optional
        Where the heat goes: `inside_mli`, `outside_mli` or `heater`, or None
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    equipment_id: NoSpaceStr
    equipment_name: str
    subsystem: NoSpaceStr
    units_on: Annotated[int, Field(ge=0)]
    eqpt_margin: Annotated[float, Field(ge=0)]
    power: dict[str, PowerQty]
    comments: str = ""
    thermal: Literal["inside_mli", "outside_mli", "heater"] | None = None

    def watts(self, mode: str, margin: bool = True) -> float:
        """
        The power the row's units draw together in one mode.

        Parameters
        ----------
        mode : str
            The mode's name
        margin : bool, optional
            Whether to add the equipment margin

        Returns
        -------
        watts : float
            In W
        """
        factor = 1 + self.eqpt_margin / 100 if margin else 1.0
        return self.units_on * float(self.power[mode].to(u.W).value) * factor


class PowerConsumption:
    """
    One power consumption file: each piece of equipment and its power by mode.

    Parameters
    ----------
    loads : list of Load
        The rows, in the file's order
    modes : list of str
        The modes, in the file's order
    source_file : Path, optional
        The file read
    source_text : str, optional
        The file's text, for the viewer
    thermal_column : bool, optional
        Whether the file has a `thermal` column
    """

    def __init__(
        self,
        loads: list[Load],
        modes: list[str],
        source_file: Path | None = None,
        source_text: str | None = None,
        thermal_column: bool = False,
    ):
        self.loads = loads
        self.modes = modes
        self.source_file = source_file
        self.source_text = source_text
        self.thermal_column = thermal_column

    @classmethod
    def from_csv(cls, csv_path: str | Path) -> "PowerConsumption":
        """
        Read and check a consumption file.

        Parameters
        ----------
        csv_path : str or Path
            The CSV file

        Returns
        -------
        consumption : PowerConsumption
            The rows and the modes

        Raises
        ------
        FileNotFoundError
            If there is no such file
        ValueError
            If a column, a mode or a row is missing, an ID repeats, a cell does not
            read, or two rows are heaters, naming the row and the column
        """
        path = Path(csv_path)
        raw = read_csv_rows(path, REQUIRED_COLUMNS)
        modes = [
            column
            for column in raw.columns
            if column not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
        ]
        if not modes:
            raise ValueError(
                f"{path.name}: no mode columns. Give one column for each mode, with "
                "the power of one unit in it."
            )
        if raw.empty:
            raise ValueError(f"{path.name}: no equipment rows")

        rows = []
        for row_number, record in enumerate(raw.to_dict("records"), start=2):
            blank = [mode for mode in modes if not str(record[mode]).strip()]
            if blank:
                raise ValueError(
                    f"{path.name}, row {row_number}: no power for the modes {blank}. "
                    "Give every mode a power, 0 W included."
                )
            fields = {name: record[name] for name in REQUIRED_COLUMNS}
            fields["comments"] = record.get("comments", "")
            fields["thermal"] = record.get(THERMAL_COLUMN, "").strip() or None
            fields["power"] = {mode: record[mode] for mode in modes}
            rows.append(fields)
        loads = validated_rows(Load, rows, path.name)

        ids = [load.equipment_id for load in loads]
        twice = sorted({name for name in ids if ids.count(name) > 1})
        if twice:
            raise ValueError(f"{path.name}: equipment IDs used more than once: {twice}")
        heaters = [load.equipment_id for load in loads if load.thermal == HEATER]
        if len(heaters) > 1:
            raise ValueError(
                f"{path.name}: more than one heater row: {heaters}. Put all the "
                "payload's heater lines together in one row."
            )
        return cls(
            loads,
            modes,
            path,
            path.read_text(encoding="utf-8"),
            THERMAL_COLUMN in raw.columns,
        )

    def mode_table(self, margin: bool = False) -> pd.DataFrame:
        """
        Each piece of equipment's power in each mode, all its units together.

        Parameters
        ----------
        margin : bool, optional
            Whether to add each row's equipment margin

        Returns
        -------
        table : pd.DataFrame
            The ID, name, subsystem, units on and margin, then each mode in W
        """
        rows = []
        for load in self.loads:
            row = {
                "equipment_id": load.equipment_id,
                "equipment_name": load.equipment_name,
                "subsystem": load.subsystem,
                "units_on": load.units_on,
                "eqpt_margin [%]": load.eqpt_margin,
            }
            row |= {f"{mode} [W]": load.watts(mode, margin) for mode in self.modes}
            rows.append(row)
        return pd.DataFrame(rows)

    def mode_totals(self) -> pd.DataFrame:
        """
        The power of all the equipment together in each mode.

        Returns
        -------
        table : pd.DataFrame
            Without and with the equipment margins, each mode in W
        """
        return pd.DataFrame(
            {
                f"{mode} [W]": [
                    sum(load.watts(mode, margin=False) for load in self.loads),
                    sum(load.watts(mode) for load in self.loads),
                ]
                for mode in self.modes
            },
            index=["without margins", "with equipment margins"],
        )


@dataclass(frozen=True)
class ConsumptionRun:
    """
    The loads of the two consumption files over a scenario run, with each row's
    equipment margin.

    Parameters
    ----------
    consumption : dict of str to PowerConsumption
        The consumption files, by group
    run : ScenarioRun
        The scenario run
    pieces : list of tuple
        The run cut where either group's mode changes: the start and end in s, and each
        group's mode
    notes : list of str
        Notes for the reader, such as unused mode columns
    """

    consumption: dict[str, PowerConsumption]
    run: ScenarioRun
    pieces: list[tuple[float, float, dict[str, str]]]
    notes: list[str]

    @cached_property
    def mode_watts(self) -> dict[str, dict[str, float]]:
        """
        The power of all of a group's equipment in each mode, with margins, in W, by
        group, then by mode.
        """
        return {
            group: {
                mode: sum(load.watts(mode) for load in consumption.loads)
                for mode in consumption.modes
            }
            for group, consumption in self.consumption.items()
        }

    def watts(self, modes: dict[str, str]) -> float:
        """
        The power of all the equipment, with each group in the mode given.

        Parameters
        ----------
        modes : dict of str to str
            Each group's mode

        Returns
        -------
        watts : float
            In W, with the equipment margins
        """
        return sum(self.mode_watts[group][mode] for group, mode in modes.items())

    @cached_property
    def modes(self) -> dict[str, np.ndarray]:
        """Each group's mode at each time of the run's grid, by group."""
        modes = {}
        for group in GROUPS:
            modes[group] = labels_at(self.run.mode[group], self.run.times)
            modes[group][-1] = self.pieces[-1][2][group]
        return modes

    @property
    def total(self) -> Quantity:
        """
        The power of all the equipment at each time of the grid, with margins, in W.
        """
        watts = sum(
            np.array([self.mode_watts[group][mode] for mode in modes])
            for group, modes in self.modes.items()
        )
        return Q_(watts, "W")

    def subsystem_power(self) -> dict[str, Quantity]:
        """
        The power of each subsystem at each time of the grid, the two files' added.

        Returns
        -------
        power : dict of str to Quantity
            In W, with margins, by subsystem, the payload's first
        """
        loads = [
            (group, load)
            for group, consumption in self.consumption.items()
            for load in consumption.loads
        ]
        power = {}
        for subsystem in dict.fromkeys(load.subsystem for _, load in loads):
            watts = 0.0
            for group, modes in self.modes.items():
                by_mode = {
                    mode: sum(
                        load.watts(mode)
                        for owner, load in loads
                        if owner == group and load.subsystem == subsystem
                    )
                    for mode in self.consumption[group].modes
                }
                watts = watts + np.array([by_mode[mode] for mode in modes])
            power[subsystem] = Q_(watts, "W")
        return power

    def energy_until(self, at: np.ndarray) -> np.ndarray:
        """
        The energy drawn from the run's start up to each time, exact.

        Parameters
        ----------
        at : ndarray
            Times in s from the run's start, inside the run

        Returns
        -------
        energy : ndarray
            In J, with margins
        """
        starts = np.array([start for start, _, _ in self.pieces])
        ends = np.array([end for _, end, _ in self.pieces])
        watts = np.array([self.watts(modes) for _, _, modes in self.pieces])
        drawn = np.concatenate([[0.0], np.cumsum(watts * (ends - starts))])
        index = np.clip(
            np.searchsorted(starts, at, side="right") - 1, 0, len(starts) - 1
        )
        return drawn[index] + watts[index] * (np.asarray(at) - starts[index])

    @cached_property
    def orbit_table(self) -> pd.DataFrame:
        """
        The loads in each whole orbit, with margins: the mean and peak in W, and the
        energy and its share in eclipse in W h.
        """
        eclipses = interval_pieces(self.run, self.run.eclipses)
        rows = []
        for number, (start, end) in enumerate(whole_orbits(self.run), start=1):
            joules = self.energy_until(np.array([start, end]))
            in_eclipse = 0.0
            for lower, upper in eclipses:
                low, high = max(lower, start), min(upper, end)
                if high > low:
                    pair = self.energy_until(np.array([low, high]))
                    in_eclipse += float(pair[1] - pair[0])
            peak = max(
                self.watts(modes)
                for lower, upper, modes in self.pieces
                if upper > start and lower < end
            )
            rows.append(
                {
                    "orbit": number,
                    "start [UTC]": (self.run.times[0] + Q_(start, "s")).utc.isot,
                    "mean load [W]": float(joules[1] - joules[0]) / (end - start),
                    "peak load [W]": peak,
                    "energy [Wh]": float(joules[1] - joules[0]) / 3600,
                    "in eclipse [Wh]": in_eclipse / 3600,
                }
            )
        return pd.DataFrame(rows)


def _merged_pieces(
    pieces: dict[str, list[tuple[float, float, str]]],
) -> list[tuple[float, float, dict[str, str]]]:
    """The run cut where either group's mode changes, with each group's mode."""
    bounds = sorted(
        {bound for row in pieces.values() for piece in row for bound in piece[:2]}
    )
    starts = {
        group: np.array([start for start, _, _ in row]) for group, row in pieces.items()
    }
    merged = []
    for lower, upper in zip(bounds[:-1], bounds[1:], strict=True):
        modes = {
            group: row[int(np.searchsorted(starts[group], lower, side="right")) - 1][2]
            for group, row in pieces.items()
        }
        merged.append((lower, upper, modes))
    return merged


def run_consumption(
    consumption: dict[str, PowerConsumption], run: ScenarioRun
) -> ConsumptionRun:
    """
    Work out the loads of the consumption files over a scenario run.

    Parameters
    ----------
    consumption : dict of str to PowerConsumption
        The two consumption files, by group
    run : ScenarioRun
        The scenario run

    Returns
    -------
    consumption_run : ConsumptionRun
        The loads, and the notes

    Raises
    ------
    ValueError
        If a group or a mode's column is missing, or the platform's file has a `thermal`
        column
    """
    missing_groups = [group for group in GROUPS if group not in consumption]
    if missing_groups:
        raise ValueError(
            f"no consumption file for the {' and the '.join(missing_groups)}"
        )
    pieces, notes = {}, []
    for group in GROUPS:
        loads = consumption[group]
        name = loads.source_file.name if loads.source_file else f"the {group}'s file"
        if group == PLATFORM and loads.thermal_column:
            raise ValueError(
                f"{name} has a '{THERMAL_COLUMN}' column, but the thermal account "
                "covers the payload only. Take the column out."
            )
        pieces[group] = sorted(
            (start, end, mode)
            for interval, mode in run.mode[group].items()
            for start, end in interval_pieces(run, interval)
        )
        needed = list(dict.fromkeys(mode for _, _, mode in pieces[group]))
        missing = [mode for mode in needed if mode not in loads.modes]
        if missing:
            raise ValueError(
                f"{name} has no column for the {group}'s modes {missing}, which the "
                f"run has. It has columns for {loads.modes}."
            )
        unused = [mode for mode in loads.modes if mode not in needed]
        if unused:
            notes.append(
                f"{name} has columns for modes that the run does not give the "
                f"{group}: {', '.join(unused)}. They are not used."
            )
    consumption = {group: consumption[group] for group in GROUPS}
    return ConsumptionRun(consumption, run, _merged_pieces(pieces), notes)
