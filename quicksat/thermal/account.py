# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The payload's heat account over a scenario run.

The payload is wrapped in MLI, taken as a perfect insulator, so heat crosses its
boundary in four places only. Every term is positive into the payload:

- **Dissipation:** the payload's rows marked `inside_mli`, at their power in each
  payload mode, without margins.
- **Heaters:** the row marked `heater`, the total of the payload's heater lines,
  without margins.
- **Heat flows:** the thermal file's fixed powers, in each payload mode.
- **Surfaces:** the heat each absorbs and emits, from `quicksat.thermal.surfaces`.

The energies follow the power's rules. The terms of the payload's modes change at
exact times between the grid's steps, so their energy comes from the mode
intervals. The absorbed powers change linearly between the steps, as the
generation does. The account is summed over each activity, each payload mode and
each whole orbit.

For each sum, the equilibrium ΔT is how far the floating surfaces would move
from their design temperatures, all by the same ΔT, for the heat out to equal
the heat in at the sum's mean powers. A fixed surface keeps its temperature.

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
from quicksat.scenario.config import PAYLOAD
from quicksat.scenario.run import ScenarioRun
from quicksat.thermal.config import PayloadThermal
from quicksat.thermal.surfaces import ABSORBED, SurfacePowers, surface_powers
from quicksat.utils.intervals import labels_at

EDGE_ON = 1e-9
"""Below this cosine of the sun's angle to a surface's normal, the sun is edge on
to the surface. The surface table does not count it as time in the sun, so that
rounding, as in sun pointing with the sun across a face, counts as none."""

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
        The start and the end, in seconds from the run's start, and the payload's
        mode, in time order
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
    Check the thermal file and the payload's consumption file against each other
    and against the run.

    Parameters
    ----------
    thermal : PayloadThermal
        The thermal file
    consumption : PowerConsumption
        The payload's consumption file
    pieces : list of tuple
        The payload's mode intervals over the run, from `payload_pieces`

    Returns
    -------
    notes : list of str
        Notes for the reader: the modes of a heat flow that the run does not
        give the payload

    Raises
    ------
    ValueError
        If the consumption file has no `thermal` column, a row has no value in
        it, the file has no column for a payload mode of the run, or a flow
        given by mode has no power for one
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
    The ΔT that would balance the heat in, with every floating surface moved by
    the same ΔT from its design temperature.

    At equilibrium, Σ εᵢσAᵢ(Tᵢ + ΔT)⁴ over the floating surfaces, plus the
    fixed surfaces' emission, equals the heat in. The left side only grows with
    ΔT, so there is one answer at most. It is found with `scipy.optimize.brentq`.

    Parameters
    ----------
    thermal : PayloadThermal
        The thermal file, for the temperatures and the fixed surfaces
    emitted : dict of str to float
        Each surface's emission at its design temperature, in W, negative
    heat_in : float
        The mean heat in, in W: the dissipation, the heaters, the flows and the
        absorbed heat

    Returns
    -------
    dt : float or None
        In K. None when no ΔT balances the heat.
    reason : str
        Why there is no ΔT, or empty
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
        """
        The scenario run.

        Returns
        -------
        run : ScenarioRun
        """
        return self.surfaces.run

    @cached_property
    def mode_watts(self) -> dict[str, dict[str, float]]:
        """
        The terms that follow the payload's mode, in each of its modes.

        Returns
        -------
        watts : dict of str to dict of str to float
            In W, without margins, by the mode's name, then by the term in
            `MODE_TERMS`
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
        """
        The payload's mode at each time of the run's grid.

        Returns
        -------
        modes : ndarray
            The mode names. The run is open at its end, so its last time takes
            the mode of its last piece.
        """
        modes = labels_at(self.run.mode[PAYLOAD], self.run.times)
        modes[-1] = self.pieces[-1][2]
        return modes

    @cached_property
    def terms(self) -> dict[str, Quantity]:
        """
        Each term of the account at each time of the grid.

        Returns
        -------
        terms : dict of str to Quantity
            In W, positive into the payload, by the term in `TERMS`. The absorbed
            and the emitted heat are the surfaces' together.
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
        """
        The net heat into the payload at each time of the grid.

        Returns
        -------
        net : Quantity
            In W: the sum of the terms
        """
        return sum(self.terms.values(), Q_(np.zeros(len(self.run.times)), "W"))

    def energies(self, start: float, end: float) -> dict[str, float]:
        """
        Each term's energy between two times.

        Parameters
        ----------
        start, end : float
            The times, in seconds from the run's start, inside the run

        Returns
        -------
        energies : dict of str to float
            In J, by the term in `TERMS`
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
        The net heat into the payload since the run's start, at each time of the
        grid.

        Returns
        -------
        energy : Quantity
            In W h, 0 at the start
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
        The spans of each activity over the run, the slew into it included.

        Returns
        -------
        spans : dict of str to list of tuple
            The start and the end of each span, in seconds from the run's start,
            by the activity's title, in the order of the scenario's list. A
            slew takes its time from the activity before it, as the attitude row
            does.
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
        The account of each activity, over all its occurrences, the slews into
        it included.

        Returns
        -------
        table : pd.DataFrame
            The activity's title and its number of occurrences, its time in
            minutes, the mean power of each term in W, the net in W and in W h,
            the equilibrium ΔT in K, and why there is none, if so
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
        The account of each payload mode, with its balancing heater power.

        The balancing heater power brings the mode's net energy over the run to
        zero: the mode's deficit before any heater, over its time. It is never
        below zero, since a heater cannot cool.

        Returns
        -------
        table : pd.DataFrame
            The mode's name, its time in minutes, the mean power of each term in
            W, the net in W and in W h, the equilibrium ΔT in K and why there is
            none, if so, and the balancing heater power in W
        """
        rows = []
        for mode in self.mode_watts:
            spans = [(start, end) for start, end, found in self.pieces if found == mode]
            row: dict = {"payload mode": mode} | self._row(spans)
            before = row["net [W]"] - row["heaters [W]"]
            row["balancing heater [W]"] = max(0.0, -before)
            rows.append(row)
        return pd.DataFrame(rows)

    @cached_property
    def orbit_table(self) -> pd.DataFrame:
        """
        The account of each whole orbit, counted as power counts them.

        Returns
        -------
        table : pd.DataFrame
            The orbit number, its start as UTC text, the mean power of each term
            in W, the net in W and in W h, and the equilibrium ΔT in K and why
            there is none, if so. Empty for a run shorter than one orbit.
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
        Each surface's properties, the sun it sees, and the heat it absorbs and
        emits over the run.

        Returns
        -------
        table : pd.DataFrame
            The surface's name, its part (blank when typed in), its area in m²,
            its absorptance and emissivity, its design temperature in K and
            whether it is fixed. Then the range of the sun's angle to its normal
            outside the umbra in degrees, the time it sees the sun in minutes, with
            the sun more than edge on (see `EDGE_ON`), its
            peak and mean sun in W, its mean view factor to the Earth, its mean
            albedo and Earth infrared in W, and its emission in W
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
        The power system file, for its self-shadowing switch
    run : ScenarioRun
        The scenario run, with its 3D model if any surface names a part
    surfaces : SurfacePowers, optional
        The surfaces' heat, from `surface_powers` with the same thermal file's
        surfaces and Earth, the same power system file and the same run. Worked
        out here if not given.

    Returns
    -------
    thermal_run : ThermalRun
        The account over the run, and the notes

    Raises
    ------
    ValueError
        If the files do not suit each other or the run, as `check_files`
        checks, or a surface's part does not suit, as `flat_geometry` checks,
        or the surfaces' heat comes from another run
    """
    pieces = payload_pieces(run)
    notes = check_files(thermal, consumption, pieces)
    if surfaces is None:
        surfaces = surface_powers(thermal, power_system, run)
    elif surfaces.run is not run:
        raise ValueError("the surfaces' heat must come from the same scenario run")
    return ThermalRun(thermal, consumption, surfaces, pieces, surfaces.notes + notes)
