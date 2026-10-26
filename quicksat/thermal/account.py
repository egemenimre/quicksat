# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The payload's heat account over a scenario run.

The payload's MLI is a perfect insulator, so heat crosses its boundary only as
dissipation, heaters, heat flows and the surfaces' heat, each positive into the payload.
The account sums them over each activity, payload mode and whole orbit, with an
equilibrium ΔT for each. `docs/explanations/payload_thermal_model.md` explains the
account and the sizing decisions.

"""

from dataclasses import dataclass
from functools import cached_property
from typing import cast

import numpy as np
import pandas as pd
import portion as P
from astropy.units import Quantity
from scipy.optimize import brentq

from quicksat import Q_, u
from quicksat.power.config import PowerSystem
from quicksat.power.consumption import (
    HEATER,
    INSIDE_MLI,
    THERMAL_COLUMN,
    THERMAL_VALUES,
    PowerConsumption,
)
from quicksat.power.orbits import (
    energy_until,
    interval_pieces,
    overlap,
    run_seconds,
    whole_orbits,
)
from quicksat.scenario.names import PAYLOAD
from quicksat.scenario.run import ScenarioRun
from quicksat.thermal.config import PayloadThermal
from quicksat.thermal.surfaces import ABSORBED, SurfacePowers, surface_powers
from quicksat.utils.intervals import labels_at

EDGE_ON = 1e-9
"""The cosine below which the sun is edge on to a surface, which the surface table does
not count as time in the sun."""

MODE_TERMS = ("dissipation", "heaters", "heat flows")
"""The terms of the account that follow the payload's mode."""

TERMS = (*MODE_TERMS, *ABSORBED, "emitted")
"""Every term of the account, in the order of the tables."""

_COLUMNS = {
    "dissipation": "dissipation [W]",
    "heaters": "heaters [W]",
    "heat flows": "heat flows [W]",
    "sun": "sun [W]",
    "albedo": "albedo [W]",
    "infrared": "Earth infrared [W]",
    "emitted": "emitted [W]",
}
"""Each term's column in the tables, as a mean power."""


def payload_pieces(run: ScenarioRun) -> list[tuple[float, float, str]]:
    """
    The run cut where the payload's mode changes.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    pieces : list of tuple
        The start and end in s from the run's start, and the payload's mode, in time
        order
    """
    return sorted(
        (start, end, mode)
        for interval, mode in run.mode[PAYLOAD].items()
        for start, end in interval_pieces(run, interval)
    )


def check_files(
    thermal: PayloadThermal,
    consumption: PowerConsumption,
    pieces: list[tuple[float, float, str]],
) -> list[str]:
    """
    Check the thermal file and the payload's consumption file against each other and the
    run.

    Parameters
    ----------
    thermal : PayloadThermal
        The thermal file
    consumption : PowerConsumption
        The payload's consumption file
    pieces : list of tuple
        The payload's mode intervals, from `payload_pieces`

    Returns
    -------
    notes : list of str
        The modes of a heat flow that the run does not give the payload

    Raises
    ------
    ValueError
        If the `thermal` column or a value in it is missing, or a run's mode has no
        column or no flow power
    """
    name = (
        consumption.source_file.name
        if consumption.source_file
        else "the payload's consumption file"
    )
    thermal_name = (
        thermal.source_file.name if thermal.source_file else "the thermal file"
    )
    values = ", ".join(THERMAL_VALUES)
    if not consumption.thermal_column:
        raise ValueError(
            f"{name} has no '{THERMAL_COLUMN}' column, which the thermal account "
            f"needs. Give each row one of {values}."
        )
    blank = [load.equipment_id for load in consumption.loads if load.thermal is None]
    if blank:
        raise ValueError(
            f"{name}: no '{THERMAL_COLUMN}' value for the rows {blank}. Give each "
            f"row one of {values}."
        )
    needed = list(dict.fromkeys(mode for _, _, mode in pieces))
    missing = [mode for mode in needed if mode not in consumption.modes]
    if missing:
        raise ValueError(
            f"{name} has no column for the payload's modes {missing}, which the run "
            f"has. It has columns for {consumption.modes}."
        )
    notes = []
    for flow, by_mode in thermal.flows_by_mode.items():
        missing = [mode for mode in needed if mode not in by_mode]
        if missing:
            raise ValueError(
                f"{thermal_name}: the heat flow '{flow}' has no power for the "
                f"payload's modes {missing}, which the run has. Give every mode a "
                "power, 0 W included."
            )
        unused = [mode for mode in by_mode if mode not in needed]
        if unused:
            notes.append(
                f"{thermal_name}: the heat flow '{flow}' has powers for modes that "
                f"the run does not give the payload: {', '.join(unused)}. They are "
                "not used."
            )
    return notes


def equilibrium_dt(
    thermal: PayloadThermal, emitted: dict[str, float], heat_in: float
) -> tuple[float | None, str]:
    """
    The ΔT, moving every floating surface alike, at which the heat out equals the heat
    in, found with `brentq`.

    Parameters
    ----------
    thermal : PayloadThermal
        The thermal file, for the temperatures and the fixed surfaces
    emitted : dict of str to float
        Each surface's emission at its design temperature, in W, negative
    heat_in : float
        The mean heat in, in W

    Returns
    -------
    dt : float or None
        In K, or None when no ΔT balances the heat
    reason : str
        Why there is none, or empty
    """
    floating = [
        name
        for name, surface in thermal.surfaces.items()
        if not surface.fixed_temperature
    ]
    if not floating:
        return None, "every surface has a fixed temperature, so none can move"
    fixed = sum(-emitted[name] for name in thermal.surfaces if name not in floating)
    target = heat_in - fixed
    kelvins = np.array(
        [float(thermal.surfaces[name].temperature.to(u.K).value) for name in floating]
    )
    # εσA of each floating surface, from its emission at its design temperature
    coefficients = np.array([-emitted[name] for name in floating]) / kelvins**4
    coldest = float(kelvins.min())

    def excess(dt: float) -> float:
        return float(coefficients @ np.clip(kelvins + dt, 0, None) ** 4) - target

    if excess(-coldest) >= 0:
        return None, (
            "more heat leaves than comes in, even with the floating surfaces at "
            "0 K, so no temperature balances it"
        )
    # with every floating surface at the coldest one's temperature, the heat out
    # would balance at this ΔT, so the answer lies below it. 1 K more keeps the
    # bound clear of the answer with one floating surface.
    high = (target / coefficients.sum()) ** 0.25 - coldest + 1.0
    return float(cast(float, brentq(excess, -coldest, high, xtol=1e-9))), ""


def run_balancing_heaters(modes: pd.DataFrame) -> pd.Series:
    """
    The heater power in each payload mode that brings the run's net energy to zero, in
    the modes that lose heat only.

    Each such mode gets the same share of its balancing power: the part of their deficit
    that the modes that gain heat do not cover.
    `docs/explanations/payload_thermal_model.md` says when to use it.

    Parameters
    ----------
    modes : pd.DataFrame
        The table by mode, with `time [min]`, `net [Wh]`, `heaters [W]` and `balancing
        heater [W]`

    Returns
    -------
    heaters : pd.Series
        In W, one per row
    """
    hours = modes["time [min]"] / 60
    before = modes["net [Wh]"] - modes["heaters [W]"] * hours
    deficit = float((modes["balancing heater [W]"] * hours).sum())
    gain = float(before.clip(lower=0).sum())
    share = min(1.0, max(0.0, 1 - gain / deficit)) if deficit > 0 else 0.0
    return modes["balancing heater [W]"] * share


@dataclass(frozen=True)
class ThermalRun:
    """
    The payload's heat account over a scenario run.

    Parameters
    ----------
    thermal : PayloadThermal
        The thermal file
    consumption : PowerConsumption
        The payload's consumption file
    surfaces : SurfacePowers
        The heat each surface absorbs and emits
    pieces : list of tuple
        The payload's mode intervals, from `payload_pieces`
    notes : list of str
        Notes for the reader
    """

    thermal: PayloadThermal
    consumption: PowerConsumption
    surfaces: SurfacePowers
    pieces: list[tuple[float, float, str]]
    notes: list[str]

    @property
    def run(self) -> ScenarioRun:
        """The scenario run."""
        return self.surfaces.run

    @cached_property
    def mode_watts(self) -> dict[str, dict[str, float]]:
        """
        The terms that follow the payload's mode, without margins, in W, by mode, then
        by term.
        """
        watts = {}
        for mode in dict.fromkeys(mode for _, _, mode in self.pieces):
            loads = self.consumption.loads
            watts[mode] = {
                "dissipation": sum(
                    load.watts(mode, margin=False)
                    for load in loads
                    if load.thermal == INSIDE_MLI
                ),
                "heaters": sum(
                    load.watts(mode, margin=False)
                    for load in loads
                    if load.thermal == HEATER
                ),
                "heat flows": sum(self.thermal.flow_watts(mode).values()),
            }
        return watts

    @cached_property
    def modes(self) -> np.ndarray:
        """The payload's mode at each time of the run's grid."""
        modes = labels_at(self.run.mode[PAYLOAD], self.run.times)
        modes[-1] = self.pieces[-1][2]
        return modes

    @cached_property
    def terms(self) -> dict[str, Quantity]:
        """
        Each term at each time of the grid, in W, positive into the payload, with the
        surfaces' heat together.
        """
        terms = {
            term: Q_(
                np.array([self.mode_watts[mode][term] for mode in self.modes]), "W"
            )
            for term in MODE_TERMS
        }
        count = len(self.run.times)
        for source in ABSORBED:
            terms[source] = Q_(
                sum(self.surfaces.absorbed[source].values(), np.zeros(count)), "W"
            )
        terms["emitted"] = Q_(np.full(count, sum(self.surfaces.emitted.values())), "W")
        return terms

    @property
    def net(self) -> Quantity:
        """The net heat into the payload at each time of the grid, in W."""
        return sum(self.terms.values(), Q_(np.zeros(len(self.run.times)), "W"))

    def energies(self, start: float, end: float) -> dict[str, float]:
        """
        Each term's energy between two times.

        Parameters
        ----------
        start, end : float
            The times, in s from the run's start, inside the run

        Returns
        -------
        energies : dict of str to float
            In J, by term
        """
        energies: dict[str, float] = dict.fromkeys(MODE_TERMS, 0.0)
        for lower, upper, mode in self.pieces:
            share = overlap([(lower, upper)], start, end)
            if share > 0:
                for term in MODE_TERMS:
                    energies[term] += self.mode_watts[mode][term] * share
        seconds = run_seconds(self.run)
        for source in ABSORBED:
            power = self.terms[source].to_value(u.W)
            pair = energy_until(seconds, np.asarray(power), np.array([start, end]))
            energies[source] = float(pair[1] - pair[0])
        energies["emitted"] = sum(self.surfaces.emitted.values()) * (end - start)
        return energies

    @cached_property
    def running_energy(self) -> Quantity:
        """
        The net heat into the payload since the run's start, at each time of the grid,
        in W h.
        """
        seconds = run_seconds(self.run)
        starts = np.array([start for start, _, _ in self.pieces])
        ends = np.array([end for _, end, _ in self.pieces])
        watts = np.array(
            [sum(self.mode_watts[mode].values()) for *_, mode in self.pieces]
        )
        before = np.concatenate([[0.0], np.cumsum(watts * (ends - starts))])
        index = np.clip(
            np.searchsorted(starts, seconds, side="right") - 1, 0, len(starts) - 1
        )
        joules = before[index] + watts[index] * (seconds - starts[index])
        for source in ABSORBED:
            power = np.asarray(self.terms[source].to_value(u.W))
            joules = joules + energy_until(seconds, power, seconds)
        joules = joules + sum(self.surfaces.emitted.values()) * seconds
        return Q_(joules, "J").to(u.W * u.h)

    def _row(self, spans: list[tuple[float, float]]) -> dict:
        """The account's columns over some spans of the run."""
        energies: dict[str, float] = dict.fromkeys(TERMS, 0.0)
        for start, end in spans:
            for term, joules in self.energies(start, end).items():
                energies[term] += joules
        time = sum(end - start for start, end in spans)
        means = {
            term: joules / time if time > 0 else np.nan
            for term, joules in energies.items()
        }
        net = sum(energies.values())
        heat_in = sum(means[term] for term in TERMS if term != "emitted")
        dt, reason = (
            equilibrium_dt(self.thermal, self.surfaces.emitted, heat_in)
            if time > 0
            else (None, "the span takes no time")
        )
        return (
            {"time [min]": time / 60}
            | {_COLUMNS[term]: means[term] for term in TERMS}
            | {
                "net [W]": net / time if time > 0 else np.nan,
                "net [Wh]": net / 3600,
                "ΔT [K]": np.nan if dt is None else dt,
                "ΔT note": reason,
            }
        )

    @cached_property
    def activity_spans(self) -> dict[str, list[tuple[float, float]]]:
        """
        Each activity's spans over the run, in s, by title, with the slew into it
        included.
        """
        owner = P.IntervalDict()
        for index, occurrence in enumerate(self.run.occurrences):
            if not occurrence.interval.empty:
                owner[occurrence.interval] = index
        for window in self.run.slews:
            owner[window.interval] = window.into
        spans: dict[str, list[tuple[float, float]]] = {
            activity.title: [] for activity in self.run.scenario.activities
        }
        for interval, index in owner.items():
            title = self.run.occurrences[index].activity.title
            spans[title].extend(interval_pieces(self.run, interval))
        return {title: sorted(found) for title, found in spans.items()}

    @cached_property
    def activity_table(self) -> pd.DataFrame:
        """
        The account of each activity, over its occurrences, slews included: the time,
        each term's mean, the net, and the equilibrium ΔT.
        """
        rows = []
        for title, spans in self.activity_spans.items():
            count = sum(
                occurrence.activity.title == title
                for occurrence in self.run.occurrences
            )
            rows.append({"activity": title, "occurrences": count} | self._row(spans))
        return pd.DataFrame(rows)

    @cached_property
    def mode_table(self) -> pd.DataFrame:
        """
        The account of each payload mode, with its two balancing heater powers, which do
        not depend on the files' heaters.

        The balancing heater power brings the mode's own net to zero, and the run
        balancing heater power the run's, from `run_balancing_heaters`.
        """
        rows = []
        for mode in self.mode_watts:
            spans = [(start, end) for start, end, found in self.pieces if found == mode]
            row: dict = {"payload mode": mode} | self._row(spans)
            before = row["net [W]"] - row["heaters [W]"]
            row["balancing heater [W]"] = max(0.0, -before)
            rows.append(row)
        table = pd.DataFrame(rows)
        table["run balancing heater [W]"] = run_balancing_heaters(table)
        return table

    @cached_property
    def orbit_table(self) -> pd.DataFrame:
        """
        The account of each whole orbit: each term's mean, the net, and the equilibrium
        ΔT.
        """
        rows = []
        for number, (start, end) in enumerate(whole_orbits(self.run), start=1):
            row = self._row([(start, end)])
            del row["time [min]"]
            rows.append(
                {
                    "orbit": number,
                    "start [UTC]": (self.run.times[0] + Q_(start, "s")).utc.isot,
                }
                | row
            )
        return pd.DataFrame(rows)

    @cached_property
    def surface_table(self) -> pd.DataFrame:
        """
        Each surface's properties, the sun it sees past `EDGE_ON`, and the heat it
        absorbs and emits over the run.
        """
        seconds = run_seconds(self.run)
        steps = np.diff(seconds)
        span = float(seconds[-1] - seconds[0])
        ends = np.array([seconds[0], seconds[-1]])
        outside_umbra = self.run.light > 0
        rows = []
        for name, geometry in self.surfaces.surfaces.items():
            entry = self.thermal.surfaces[name]
            angles = np.degrees(
                np.arccos(
                    np.clip(self.surfaces.sun_cosines[name][outside_umbra], -1, 1)
                )
            )
            means = {}
            for source in ABSORBED:
                power = self.surfaces.absorbed[source][name]
                means[source] = (
                    float(np.diff(energy_until(seconds, power, ends))[0]) / span
                )
            sun = self.surfaces.absorbed["sun"][name]
            sees = ((sun > 0) & (self.surfaces.sun_cosines[name] > EDGE_ON)).astype(
                float
            )
            rows.append(
                {
                    "surface": name,
                    "part": entry.part or "",
                    "area [m2]": geometry.area.to_value(u.m**2),
                    "absorptance": float(entry.absorptance.to_value(u.one)),
                    "emissivity": float(entry.emissivity.to_value(u.one)),
                    "temperature [K]": float(entry.temperature.to(u.K).value),
                    "fixed": entry.fixed_temperature,
                    "lowest sun angle [deg]": angles.min() if angles.size else np.nan,
                    "highest sun angle [deg]": angles.max() if angles.size else np.nan,
                    "in sun [min]": float(steps @ ((sees[:-1] + sees[1:]) / 2)) / 60,
                    "peak sun [W]": float(sun.max()),
                    "mean sun [W]": means["sun"],
                    "mean view factor": float(
                        np.diff(
                            energy_until(
                                seconds, self.surfaces.view_factors[name], ends
                            )
                        )[0]
                    )
                    / span,
                    "mean albedo [W]": means["albedo"],
                    "mean Earth infrared [W]": means["infrared"],
                    "emitted [W]": self.surfaces.emitted[name],
                }
            )
        return pd.DataFrame(rows)


def run_thermal(
    thermal: PayloadThermal,
    consumption: PowerConsumption,
    power_system: PowerSystem,
    run: ScenarioRun,
    surfaces: SurfacePowers | None = None,
) -> ThermalRun:
    """
    Work out the payload's heat account over a scenario run.

    Parameters
    ----------
    thermal : PayloadThermal
        The thermal file
    consumption : PowerConsumption
        The payload's consumption file, with its `thermal` column
    power_system : PowerSystem
        The power system file, for the self-shadowing
    run : ScenarioRun
        The scenario run
    surfaces : SurfacePowers, optional
        The surfaces' heat for the same files and run, worked out here if not given

    Returns
    -------
    thermal_run : ThermalRun
        The account, and the notes

    Raises
    ------
    ValueError
        If the files do not suit each other or the run, or the surfaces' heat comes from
        another run
    """
    pieces = payload_pieces(run)
    notes = check_files(thermal, consumption, pieces)
    if surfaces is None:
        surfaces = surface_powers(thermal, power_system, run)
    elif surfaces.run is not run:
        raise ValueError("the surfaces' heat must come from the same scenario run")
    return ThermalRun(thermal, consumption, surfaces, pieces, surfaces.notes + notes)
