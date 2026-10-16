# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power consumption file, and the loads it gives over a scenario run.

The file is a CSV, usually `power_consumption.csv`, with one row for each piece
of equipment that draws power. Equipment that draws none, such as the structure,
is left out. The columns are

- `equipment_id`, a short name with no spaces, which no other row has;
- `equipment_name`, free text;
- `subsystem`, such as `ADCS`, with no spaces;
- `units_on`, how many units draw power, such as 1 of a cold-redundant pair;
- `eqpt_margin`, the equipment's margin in percent, such as `5`;
- one column for each mode, with the power of one unit in that mode, such as
  `10 W`, averaged over the mode;
- `comments`, optional free text.

The scenario names the modes, and this file says what each draws. Every mode
the run has needs its column, `slew` included when the scenario has slews: the
run gives the mode row that name while the body turns. Every cell of a mode
column needs a power, `0 W` included, so that no mode is assumed to equal
another. Columns for modes the run does not have are allowed, and noted.

At each time of the run, each row draws its units' power in the mode of that
time, with its margin. The modes change at exact times between the steps of the
grid, so the energy is worked out from the mode intervals, not from the grid.

"""

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
from astropy.units import Quantity
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quicksat import Q_, u
from quicksat.power.orbits import interval_pieces, whole_orbits
from quicksat.scenario.run import ScenarioRun
from quicksat.utils.intervals import labels_at
from quicksat.utils.parser_helpers import NoSpaceStr, PowerQty

REQUIRED_COLUMNS = (
    "equipment_id",
    "equipment_name",
    "subsystem",
    "units_on",
    "eqpt_margin",
)
"""The columns every consumption file needs, before the modes."""

OPTIONAL_COLUMNS = ("comments",)
"""Columns that may be there, and are not modes."""


class Load(BaseModel):
    """
    One row of the consumption file: a piece of equipment and its power by mode.

    Each row is checked on load, so a bad cell gives an error that names its row
    and column, rather than failing later in the arithmetic.

    Parameters
    ----------
    equipment_id : str
        Short identifier, with no spaces, such as `star_tracker`
    equipment_name : str
        Full name, free text
    subsystem : str
        The subsystem, with no spaces, such as `ADCS`
    units_on : int
        How many units draw power. Zero keeps a row in the file that draws none.
    eqpt_margin : float
        The equipment's margin, in percent: `5` means 5%
    power : dict of str to Quantity
        The power of one unit in each mode, by the mode's name
    comments : str, optional
        Free text notes
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    equipment_id: NoSpaceStr
    equipment_name: str
    subsystem: NoSpaceStr
    units_on: Annotated[int, Field(ge=0)]
    eqpt_margin: Annotated[float, Field(ge=0)]
    power: dict[str, PowerQty]
    comments: str = ""

    def watts(self, mode: str, margin: bool = True) -> float:
        """
        The power that the row's units draw together in one mode.

        Parameters
        ----------
        mode : str
            The mode's name
        margin : bool, optional
            Whether to add the equipment margin. True by default.

        Returns
        -------
        watts : float
            In W
        """
        factor = 1 + self.eqpt_margin / 100 if margin else 1.0
        return self.units_on * float(self.power[mode].to(u.W).value) * factor


class PowerConsumption:
    """
    The power consumption file: each piece of equipment and its power by mode.

    Parameters
    ----------
    loads : list of Load
        The rows, in the order of the file
    modes : list of str
        The modes, in the order of the file's columns
    source_file : Path, optional
        The file the rows were read from
    source_text : str, optional
        The file's text, as read, for the viewer to show
    """

    def __init__(
        self,
        loads: list[Load],
        modes: list[str],
        source_file: Path | None = None,
        source_text: str | None = None,
    ):
        self.loads = loads
        self.modes = modes
        self.source_file = source_file
        self.source_text = source_text

    @classmethod
    def from_csv(cls, csv_path: str | Path) -> "PowerConsumption":
        """
        Read and check a consumption file.

        Parameters
        ----------
        csv_path : str | Path
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
            If a column is missing, there is no mode column or no row, an
            equipment ID is used twice, or a cell does not read. The message
            names the row and the column.
        """
        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"File does not exist: {csv_path}")
        path = Path(csv_path)
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, skipinitialspace=True)
        raw.columns = [str(column).strip() for column in raw.columns]
        missing = [name for name in REQUIRED_COLUMNS if name not in raw.columns]
        if missing:
            raise ValueError(f"{path.name}: missing columns {missing}")
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

        loads = []
        for row_number, record in enumerate(raw.to_dict("records"), start=2):
            blank = [mode for mode in modes if not str(record[mode]).strip()]
            if blank:
                raise ValueError(
                    f"{path.name}, row {row_number}: no power for the modes {blank}. "
                    "Give every mode a power, 0 W included."
                )
            fields = {name: record[name] for name in REQUIRED_COLUMNS}
            fields["comments"] = record.get("comments", "")
            fields["power"] = {mode: record[mode] for mode in modes}
            try:
                loads.append(Load(**fields))
            except ValidationError as exc:
                raise ValueError(f"{path.name}, row {row_number}:\n{exc}") from exc

        ids = [load.equipment_id for load in loads]
        twice = sorted({name for name in ids if ids.count(name) > 1})
        if twice:
            raise ValueError(f"{path.name}: equipment IDs used more than once: {twice}")
        return cls(loads, modes, path, path.read_text(encoding="utf-8"))

    def mode_table(self, margin: bool = False) -> pd.DataFrame:
        """
        Each piece of equipment's power in each mode, all its units together.

        Parameters
        ----------
        margin : bool, optional
            Whether to add each row's equipment margin. False by default.

        Returns
        -------
        table : pd.DataFrame
            The equipment ID, name, subsystem, units on and margin in percent,
            then one column for each mode, in W
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
            One row without the margins and one with the equipment margins, and
            one column for each mode, in W
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
    The loads of a consumption file over a scenario run.

    The power is the equipment's, with each row's equipment margin. The power
    budget adds the system margin.

    Parameters
    ----------
    consumption : PowerConsumption
        The consumption file
    run : ScenarioRun
        The scenario run
    pieces : list of tuple
        The run's mode intervals, as the start and the end in seconds from the
        run's start, and the mode, in time order
    notes : list of str
        Notes for the reader, such as columns for modes the run does not have
    """

    consumption: PowerConsumption
    run: ScenarioRun
    pieces: list[tuple[float, float, str]]
    notes: list[str]

    @cached_property
    def mode_watts(self) -> dict[str, float]:
        """
        The power of all the equipment in each mode, with the equipment margins.

        Returns
        -------
        watts : dict of str to float
            In W, by the mode's name
        """
        return {
            mode: sum(load.watts(mode) for load in self.consumption.loads)
            for mode in self.consumption.modes
        }

    @cached_property
    def modes(self) -> np.ndarray:
        """
        The mode at each time of the run's grid.

        Returns
        -------
        modes : ndarray
            The mode names. The run is open at its end, so its last time takes
            the mode of its last piece.
        """
        modes = labels_at(self.run.mode, self.run.times)
        modes[-1] = self.pieces[-1][2]
        return modes

    @property
    def total(self) -> Quantity:
        """
        The power of all the equipment at each time of the grid.

        Returns
        -------
        total : Quantity
            In W, with the equipment margins
        """
        return Q_([self.mode_watts[mode] for mode in self.modes], "W")

    def subsystem_power(self) -> dict[str, Quantity]:
        """
        The power of each subsystem at each time of the grid.

        Returns
        -------
        power : dict of str to Quantity
            In W, with the equipment margins, by subsystem, in the order the
            file first names them
        """
        subsystems = dict.fromkeys(load.subsystem for load in self.consumption.loads)
        watts = {
            subsystem: {
                mode: sum(
                    load.watts(mode)
                    for load in self.consumption.loads
                    if load.subsystem == subsystem
                )
                for mode in self.consumption.modes
            }
            for subsystem in subsystems
        }
        return {
            subsystem: Q_([by_mode[mode] for mode in self.modes], "W")
            for subsystem, by_mode in watts.items()
        }

    def energy_until(self, at: np.ndarray) -> np.ndarray:
        """
        The energy drawn from the start of the run up to each given time.

        The power holds steady through each mode interval, so the energy is exact.

        Parameters
        ----------
        at : ndarray
            Times in seconds from the run's start, inside the run

        Returns
        -------
        energy : ndarray
            In joules, with the equipment margins, one for each time
        """
        starts = np.array([start for start, _, _ in self.pieces])
        ends = np.array([end for _, end, _ in self.pieces])
        watts = np.array([self.mode_watts[mode] for _, _, mode in self.pieces])
        drawn = np.concatenate([[0.0], np.cumsum(watts * (ends - starts))])
        index = np.clip(
            np.searchsorted(starts, at, side="right") - 1, 0, len(starts) - 1
        )
        return drawn[index] + watts[index] * (np.asarray(at) - starts[index])

    @cached_property
    def orbit_table(self) -> pd.DataFrame:
        """
        The loads in each whole orbit of the run.

        Returns
        -------
        table : pd.DataFrame
            The orbit number, its start as UTC text, the mean and the peak load
            in W, the energy drawn in W h, and the part of it drawn in eclipse in
            W h. All with the equipment margins. Empty for a run shorter than one
            orbit.
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
                self.mode_watts[mode]
                for lower, upper, mode in self.pieces
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


def run_consumption(consumption: PowerConsumption, run: ScenarioRun) -> ConsumptionRun:
    """
    Work out the loads of a consumption file over a scenario run.

    Parameters
    ----------
    consumption : PowerConsumption
        The consumption file
    run : ScenarioRun
        The scenario run

    Returns
    -------
    consumption_run : ConsumptionRun
        The loads over the run, and the notes

    Raises
    ------
    ValueError
        If the run has a mode that the file has no column for
    """
    pieces = sorted(
        (start, end, mode)
        for interval, mode in run.mode.items()
        for start, end in interval_pieces(run, interval)
    )
    needed = list(dict.fromkeys(mode for _, _, mode in pieces))
    missing = [mode for mode in needed if mode not in consumption.modes]
    if missing:
        raise ValueError(
            f"the consumption file has no column for the modes {missing}, which the "
            f"run has. It has columns for {consumption.modes}."
        )
    unused = [mode for mode in consumption.modes if mode not in needed]
    notes = (
        [
            f"The consumption file has columns for modes this run does not have: "
            f"{', '.join(unused)}. They are not used."
        ]
        if unused
        else []
    )
    return ConsumptionRun(consumption, run, pieces, notes)
