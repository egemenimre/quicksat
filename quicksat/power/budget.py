# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power budget: generation and consumption over a run, through the battery.

At each step, a surplus charges the battery until it is full, and a shortfall comes from
it, each through its conditioning path. Three checks follow: the battery's charge, each
whole orbit's energy balance, and the loads met. `docs/power/power_budget_ref.ipynb` and
`docs/explanations/power_model.md` explain the steps and the checks.

"""

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.power.config import Battery, Conditioning, PowerSystem
from quicksat.power.consumption import ConsumptionRun
from quicksat.power.generation import GenerationRun
from quicksat.power.orbits import energy_until, run_seconds, whole_orbits

FLOWS = (
    "generated",
    "consumed",
    "array_regulator",
    "battery_charge",
    "battery_discharge",
    "distribution",
    "unused",
    "stored",
    "drawn",
    "unmet",
)
"""The energies the budget follows in each step: the array's, the loads', each
conditioning loss, the unused, the battery's in and out, and the loads' lack."""

LOSSES = ("array_regulator", "battery_charge", "battery_discharge", "distribution")
"""The flows that are conditioning losses."""


@dataclass(frozen=True)
class PowerCheck:
    """
    One check of the budget, as the viewer shows it.

    Parameters
    ----------
    name : str
        What is checked
    status : str
        `ok`, `warn` or `fail`
    detail : str
        What was found
    """

    name: str
    status: str
    detail: str


def simulate(
    generated: np.ndarray,
    consumed: np.ndarray,
    battery: Battery,
    conditioning: Conditioning,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """
    Follow the battery's charge through the steps of a run.

    Parameters
    ----------
    generated : ndarray
        The array's energy in each step, in J, shape (n - 1,)
    consumed : ndarray
        The loads' energy in each step, all margins in, in J, shape (n - 1,)
    battery : Battery
        The battery
    conditioning : Conditioning
        The efficiencies

    Returns
    -------
    charge : ndarray
        The charge at each time, as a share of the usable capacity, shape (n,)
    flows : dict of str to ndarray
        Each of `FLOWS` in each step, in J
    """
    regulator = float(conditioning.array_regulator.to(u.dimensionless_unscaled).value)
    charge_eff = float(conditioning.battery_charge.to(u.dimensionless_unscaled).value)
    discharge_eff = float(
        conditioning.battery_discharge.to(u.dimensionless_unscaled).value
    )
    distribution = float(conditioning.distribution.to(u.dimensionless_unscaled).value)
    usable = float(battery.usable.to(u.J).value)

    flows = {name: np.zeros(len(generated)) for name in FLOWS}
    flows["generated"] = generated.copy()
    flows["consumed"] = consumed.copy()
    held = float(battery.initial_charge.to(u.dimensionless_unscaled).value) * usable
    charge = [held / usable]
    for k, (array, load) in enumerate(zip(generated, consumed, strict=True)):
        need = load / distribution
        flows["distribution"][k] = need - load
        at_bus = array * regulator
        if at_bus >= need:
            stored = min((at_bus - need) * charge_eff, usable - held)
            taken = stored / charge_eff
            spare = (at_bus - need - taken) / regulator
            flows["unused"][k] = spare
            flows["array_regulator"][k] = (array - spare) * (1 - regulator)
            flows["battery_charge"][k] = taken - stored
            flows["stored"][k] = stored
            held += stored
        else:
            flows["array_regulator"][k] = array * (1 - regulator)
            wanted = (need - at_bus) / discharge_eff
            drawn = min(wanted, held)
            flows["drawn"][k] = drawn
            flows["battery_discharge"][k] = drawn * (1 - discharge_eff)
            flows["unmet"][k] = (wanted - drawn) * discharge_eff * distribution
            held -= drawn
        charge.append(held / usable)
    return np.array(charge), flows


@dataclass(frozen=True)
class BudgetRun:
    """
    The power budget over a run: the loads, the battery's charge and the checks.

    Parameters
    ----------
    power_system : PowerSystem
        The power system file
    generation : GenerationRun
        The generation over the run
    consumption : ConsumptionRun
        The loads over the run
    load : Quantity
        The loads on the grid, all margins in, in W
    charge : ndarray
        The battery's charge on the grid, as a share of its usable capacity
    flows : dict of str to ndarray
        Each of `FLOWS` in each step, in J
    """

    power_system: PowerSystem
    generation: GenerationRun
    consumption: ConsumptionRun
    load: Quantity
    charge: np.ndarray
    flows: dict[str, np.ndarray]

    @property
    def battery(self) -> Battery:
        """The battery."""
        assert self.power_system.battery is not None  # run_budget checks it
        return self.power_system.battery

    @property
    def lowest_allowed(self) -> float:
        """
        The lowest charge the battery may reach, as a share: 1 less its maximum depth.
        """
        return 1 - float(
            self.battery.max_depth_of_discharge.to(u.dimensionless_unscaled).value
        )

    def flows_between(self, start: float, end: float) -> dict[str, float]:
        """
        Each flow between two times, counting a cut step for its share inside them.

        Parameters
        ----------
        start, end : float
            The times, in s from the run's start

        Returns
        -------
        flows : dict of str to float
            Each of `FLOWS`, in W h
        """
        seconds = run_seconds(self.generation.run)
        low, high = seconds[:-1], seconds[1:]
        share = np.clip(
            (np.minimum(high, end) - np.maximum(low, start)) / (high - low), 0, 1
        )
        return {name: float(flow @ share) / 3600 for name, flow in self.flows.items()}

    def _charge_at(self, times: np.ndarray) -> np.ndarray:
        """The charge at times between the steps, taken linearly."""
        return np.interp(times, run_seconds(self.generation.run), self.charge)

    @property
    def _unused_to_battery(self) -> float:
        """The share of unused array energy that would reach the battery."""
        conditioning = self.power_system.conditioning
        assert conditioning is not None  # run_budget checks it
        return float(
            conditioning.array_regulator.to(u.dimensionless_unscaled).value
        ) * float(conditioning.battery_charge.to(u.dimensionless_unscaled).value)

    @cached_property
    def orbit_table(self) -> pd.DataFrame:
        """
        Where the energy goes in each whole orbit, in W h, with the margin and the
        battery's charge in percent.
        """
        seconds = run_seconds(self.generation.run)
        rows = []
        for number, (start, end) in enumerate(whole_orbits(self.generation.run), 1):
            flows = self.flows_between(start, end)
            inside = (seconds > start) & (seconds < end)
            edges = self._charge_at(np.array([start, end]))
            lowest = min(edges.min(), self.charge[inside].min(initial=1.0))
            rows.append(
                {
                    "orbit": number,
                    "generated [Wh]": flows["generated"],
                    "consumed [Wh]": flows["consumed"],
                    "losses [Wh]": sum(flows[name] for name in LOSSES),
                    "unused [Wh]": flows["unused"],
                    "into battery [Wh]": flows["stored"] - flows["drawn"],
                    "margin [Wh]": flows["stored"]
                    - flows["drawn"]
                    + flows["unused"] * self._unused_to_battery,
                    "charge at start [%]": 100 * edges[0],
                    "lowest charge [%]": 100 * lowest,
                    "charge at end [%]": 100 * edges[1],
                }
            )
        return pd.DataFrame(rows)

    @cached_property
    def loss_table(self) -> pd.DataFrame:
        """Each conditioning path's loss in each whole orbit, in W h."""
        rows = []
        for number, (start, end) in enumerate(whole_orbits(self.generation.run), 1):
            flows = self.flows_between(start, end)
            rows.append(
                {"orbit": number}
                | {f"{name.replace('_', ' ')} [Wh]": flows[name] for name in LOSSES}
            )
        return pd.DataFrame(rows)

    @cached_property
    def checks(self) -> list[PowerCheck]:
        """
        The three checks, in order: the battery's charge, the energy balance, and the
        loads met.
        """
        lowest = float(self.charge.min())
        allowed = self.lowest_allowed
        charge = PowerCheck(
            "Battery charge",
            "ok" if lowest >= allowed else "fail",
            f"The lowest charge is {100 * lowest:.1f}%, "
            f"{'above' if lowest >= allowed else 'below'} the {100 * allowed:.0f}% "
            f"that a {100 * (1 - allowed):.0f}% depth of discharge allows.",
        )

        table = self.orbit_table
        margins = [] if table.empty else table["margin [Wh]"].tolist()
        if not margins:
            balance = PowerCheck(
                "Energy balance",
                "warn",
                "The run is shorter than one orbit, so the balance is not checked.",
            )
        elif min(margins) < -1e-6:
            losing = [
                f"orbit {number}, {-margin:.1f} W h short"
                for number, margin in enumerate(margins, 1)
                if margin < -1e-6
            ]
            balance = PowerCheck(
                "Energy balance",
                "fail",
                "The battery loses more than the array can give back in "
                + "; ".join(losing)
                + ". Over more orbits, it would run down.",
            )
        else:
            balance = PowerCheck(
                "Energy balance",
                "ok",
                f"Each of the {len(margins)} whole orbits has energy to spare: "
                f"{min(margins):.1f} W h at least.",
            )

        unmet = float(self.flows["unmet"].sum()) / 3600
        met = PowerCheck(
            "Loads met",
            "ok" if unmet == 0 else "fail",
            "The battery never runs flat."
            if unmet == 0
            else f"The battery runs flat, and the loads lack {unmet:.1f} W h.",
        )
        return [charge, balance, met]

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(check.status == "ok" for check in self.checks)


def run_budget(
    power_system: PowerSystem,
    generation: GenerationRun,
    consumption: ConsumptionRun,
) -> BudgetRun:
    """
    Work out the power budget over a run.

    Parameters
    ----------
    power_system : PowerSystem
        The power system file, with its battery, conditioning and system margin
    generation : GenerationRun
        The generation over the run
    consumption : ConsumptionRun
        The loads over the same run

    Returns
    -------
    budget : BudgetRun
        The budget

    Raises
    ------
    ValueError
        If the battery, the conditioning or the system margin is missing, or the two
        come from different runs
    """
    missing = [
        name
        for name in ("battery", "conditioning", "system_margin")
        if getattr(power_system, name) is None
    ]
    if missing:
        raise ValueError(
            f"the power budget needs {', '.join(missing)} in the power system file"
        )
    if generation.run is not consumption.run:
        raise ValueError(
            "the generation and the consumption must come from the same scenario run"
        )
    assert power_system.battery is not None and power_system.conditioning is not None
    assert power_system.system_margin is not None

    seconds = run_seconds(generation.run)
    generated = np.diff(
        energy_until(seconds, np.asarray(generation.total.to_value(u.W)), seconds)
    )
    margin = 1 + float(power_system.system_margin.to(u.dimensionless_unscaled).value)
    consumed = np.diff(consumption.energy_until(seconds)) * margin
    charge, flows = simulate(
        generated, consumed, power_system.battery, power_system.conditioning
    )
    return BudgetRun(
        power_system,
        generation,
        consumption,
        Q_(consumption.total.to(u.W).value * margin, "W"),
        charge,
        flows,
    )


def budget_summary(budget: BudgetRun) -> list[dict[str, str | bool]]:
    """
    The budget's figures for the viewer's summary, the means over the whole orbits.

    Parameters
    ----------
    budget : BudgetRun
        The budget

    Returns
    -------
    summary : list of dict
        Each with a `label`, a `value`, a `unit`, and whether it is a `headline` card
    """
    orbits = whole_orbits(budget.generation.run)
    seconds = run_seconds(budget.generation.run)
    start, end = (orbits[0][0], orbits[-1][1]) if orbits else (0.0, seconds[-1])
    flows = budget.flows_between(start, end)
    count = max(len(orbits), 1)
    span = end - start

    def item(label, value, unit, headline=False):
        return {"label": label, "value": value, "unit": unit, "headline": headline}

    return [
        item("Lowest charge", f"{100 * budget.charge.min():.1f}", "%", True),
        item("Mean generated", f"{flows['generated'] * 3600 / span:.0f}", "W", True),
        item("Mean consumed", f"{flows['consumed'] * 3600 / span:.0f}", "W", True),
        item(
            "Usable capacity", f"{budget.battery.usable.to_value(u.W * u.h):.0f}", "W h"
        ),
        item("Deepest discharge", f"{100 * (1 - budget.charge.min()):.1f}", "%"),
        item("Unused per orbit", f"{flows['unused'] / count:.0f}", "W h"),
        item(
            "Conditioning losses per orbit",
            f"{sum(flows[name] for name in LOSSES) / count:.0f}",
            "W h",
        ),
        item("Peak load", f"{float(budget.load.max().to(u.W).value):.0f}", "W"),
    ]
