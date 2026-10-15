# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the power budget: the battery step by step, where the energy goes, the
checks, and the viewer's `power.js`.
"""

import json

import numpy as np
import pytest

from quicksat import Q_, u
from quicksat.power.budget import LOSSES, budget_summary, run_budget, simulate
from quicksat.power.config import Battery, Conditioning, PowerSystem
from quicksat.power.viewer import DATA_FILE, PAGE_FILE, power_data, write_power_viewer
from quicksat.scenario.viewer import DATA_FILE as SCENARIO_FILE

BATTERY = Battery(
    capacity=Q_(100, "W h"),
    capacity_factor=Q_(1, ""),
    max_depth_of_discharge=Q_(30, "%"),
    initial_charge=Q_(50, "%"),
)
"""A 100 W h battery, half full."""

IDEAL = Conditioning(
    array_regulator=Q_(1, ""),
    battery_charge=Q_(1, ""),
    battery_discharge=Q_(1, ""),
    distribution=Q_(1, ""),
)
"""Conditioning with no losses."""

LOSSY = Conditioning(
    array_regulator=Q_(0.96, ""),
    battery_charge=Q_(0.95, ""),
    battery_discharge=Q_(0.95, ""),
    distribution=Q_(0.97, ""),
)
"""The sample's conditioning."""

HOUR = 3600.0
"""Joules in a W h."""


def balance(flows: dict) -> float:
    """What comes in, less what goes out, over all the steps, in J."""
    come = flows["generated"].sum() + flows["drawn"].sum()
    go = flows["consumed"].sum() + flows["stored"].sum() + flows["unused"].sum()
    return float(come - go - sum(flows[name].sum() for name in LOSSES))


# ------------------------------------------------------------------ the steps


def test_a_surplus_fills_the_battery_and_the_rest_is_unused():
    # 10 W h spare a step, and 50 W h of room
    charge, flows = simulate(
        np.full(8, 30 * HOUR), np.full(8, 20 * HOUR), BATTERY, IDEAL
    )
    assert charge[:7] == pytest.approx([0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0])
    assert flows["unused"].sum() / HOUR == pytest.approx(30)
    assert balance(flows) == pytest.approx(0)


def test_a_shortfall_comes_from_the_battery_until_it_is_flat():
    charge, flows = simulate(np.zeros(8), np.full(8, 20 * HOUR), BATTERY, IDEAL)
    assert charge[:4] == pytest.approx([0.5, 0.3, 0.1, 0.0])
    assert charge[-1] == 0
    # 160 W h wanted, 50 W h held
    assert flows["unmet"].sum() / HOUR == pytest.approx(110)


def test_each_path_takes_its_loss():
    # one step in sunlight with a surplus, one in eclipse with none; the battery
    # neither fills nor runs flat
    charge, flows = simulate(
        np.array([150 * HOUR, 0.0]), np.array([97 * HOUR, 48.5 * HOUR]), BATTERY, LOSSY
    )
    # the loads need 100 and 50 W h at the bus; the array gives 144 there
    assert flows["distribution"] / HOUR == pytest.approx([3, 1.5])
    assert flows["array_regulator"] / HOUR == pytest.approx([6, 0])
    stored = (144 - 100) * 0.95
    assert flows["stored"][0] / HOUR == pytest.approx(stored)
    assert flows["battery_charge"][0] / HOUR == pytest.approx(144 - 100 - stored)
    assert flows["unused"].sum() == 0
    # the second step draws 50 / 0.95 from the battery
    assert flows["drawn"][1] / HOUR == pytest.approx(50 / 0.95)
    assert flows["battery_discharge"][1] / HOUR == pytest.approx(50 / 0.95 - 50)
    assert charge[2] == pytest.approx(0.5 + (stored - 50 / 0.95) / 100)
    assert balance(flows) == pytest.approx(0, abs=1e-6)


# ------------------------------------------------------------------- the run


def test_the_battery_starts_full_and_the_energy_balances(budget):
    assert budget.charge[0] == 1
    assert budget.charge.min() >= budget.lowest_allowed
    assert balance(budget.flows) == pytest.approx(0, abs=1e-3)
    assert budget.flows["unmet"].sum() == 0


def test_the_load_carries_the_system_margin(budget, consumption_run):
    np.testing.assert_allclose(
        budget.load.to_value(u.W), consumption_run.total.to_value(u.W) * 1.05
    )


def test_the_orbit_table_follows_the_energy(budget, generation_run):
    (row,) = budget.orbit_table.to_dict("records")
    assert row["generated [Wh]"] == pytest.approx(
        generation_run.orbit_table["energy [Wh]"].iloc[0], rel=1e-9
    )
    out = row["consumed [Wh]"] + row["losses [Wh]"] + row["unused [Wh]"]
    assert row["generated [Wh]"] == pytest.approx(out + row["into battery [Wh]"])
    assert row["charge at start [%]"] == pytest.approx(100)
    assert row["lowest charge [%]"] == pytest.approx(100 * budget.charge.min())
    (losses,) = budget.loss_table.to_dict("records")
    assert sum(
        value for key, value in losses.items() if key != "orbit"
    ) == pytest.approx(row["losses [Wh]"])


def test_the_checks_pass_for_the_fixture(budget):
    assert [check.name for check in budget.checks] == [
        "Battery charge",
        "Energy balance",
        "Loads met",
    ]
    assert budget.passed
    assert budget.checks[1].detail.startswith("Each of the 1 whole orbits has energy")


def heavier(power_system: PowerSystem, margin: str) -> PowerSystem:
    """The fixture's power system with a larger system margin."""
    return power_system.model_copy(update={"system_margin": Q_(margin)})


def test_a_budget_that_loses_charge_each_orbit_fails(power_system, budget):
    # one orbit only: the battery starts full, so it ends lower without filling
    heavy = run_budget(
        heavier(power_system, "35 %"), budget.generation, budget.consumption
    )
    statuses = {check.name: check.status for check in heavy.checks}
    assert statuses["Energy balance"] == "fail"
    assert "orbit 1" in heavy.checks[1].detail
    assert heavy.orbit_table["margin [Wh]"].iloc[0] < 0
    assert statuses["Loads met"] == "ok"


def test_a_battery_that_runs_flat_fails_every_check(power_system, budget):
    flat = run_budget(
        heavier(power_system, "400 %"), budget.generation, budget.consumption
    )
    statuses = [check.status for check in flat.checks]
    assert statuses == ["fail", "fail", "fail"]
    assert flat.charge.min() == 0
    assert not flat.passed


def test_a_run_shorter_than_an_orbit_is_not_balanced(
    power_system, consumption, short_run
):
    from quicksat.power.consumption import run_consumption

    short = run_budget(
        power_system, short_run, run_consumption(consumption, short_run.run)
    )
    balance_check = short.checks[1]
    assert balance_check.status == "warn"
    assert short.orbit_table.empty


def test_the_budget_needs_a_battery_and_the_conditioning(power_system, budget):
    bare = power_system.model_copy(update={"battery": None, "system_margin": None})
    with pytest.raises(ValueError, match="needs battery, system_margin"):
        run_budget(bare, budget.generation, budget.consumption)


def test_the_budget_needs_one_run(power_system, budget, short_run, consumption):
    from quicksat.power.consumption import run_consumption

    other = run_consumption(consumption, short_run.run)
    with pytest.raises(ValueError, match="same scenario run"):
        run_budget(power_system, budget.generation, other)


def test_the_summary_gives_the_headlines(budget):
    summary = budget_summary(budget)
    headlines = [item["label"] for item in summary if item["headline"]]
    assert headlines == ["Lowest charge", "Mean generated", "Mean consumed"]
    lowest = next(item for item in summary if item["label"] == "Lowest charge")
    assert lowest["value"] == f"{100 * budget.charge.min():.1f}"


# ----------------------------------------------------------------- the viewer


def read_js(path) -> dict:
    """The data of a `.js` file that sets one `window.quicksat` key."""
    text = path.read_text()
    # the data is the object assigned after the line that starts window.quicksat
    return json.loads(text[text.index(" = {") + 3 :].rstrip().rstrip(";"))


def test_the_viewer_folder_holds_both_data_files(budget, tmp_path):
    page = write_power_viewer(budget, tmp_path)
    assert page == tmp_path / PAGE_FILE
    scenario = read_js(tmp_path / SCENARIO_FILE)
    power = read_js(tmp_path / DATA_FILE)
    assert power["scenario_id"] == scenario["id"]
    assert power["format"] == "quicksat-power"
    steps = len(scenario["grid"]["t_s"])
    grid = power["grid"]
    for name in ("generated_w", "consumed_w", "soc"):
        assert len(grid[name]) == steps
    panels = power["spacecraft"]["panels"]
    assert len(grid["sun_cos"]) == len(grid["panel_w"]) == len(panels)
    assert all(len(values) == steps for values in grid["sun_cos"] + grid["panel_w"])
    assert power["battery"]["max_depth_of_discharge"] == pytest.approx(0.30)
    assert [check["status"] for check in power["checks"]] == ["ok", "ok", "ok"]
    assert [block["title"] for block in power["setup"]] == [
        "Panels",
        "Generation",
        "Battery",
        "Consumption by mode",
    ]


def test_the_panels_are_placed_as_the_model_draws_them(budget):
    data = power_data(budget, "id")
    panels = {panel["name"]: panel for panel in data["spacecraft"]["panels"]}
    deck = panels["deck"]
    assert deck["axis"] == 2
    assert deck["normal"] == [0.0, 0.0, -1.0]
    assert deck["articulation"] is None
    assert panels["wing +y outer"]["articulation"] == "wing +y"
    assert panels["wing +y outer"]["size_m"] == pytest.approx([0.66, 0.61])
    # the typed-in panel sits on the body's +x face
    side = panels["side +x"]
    assert side["axis"] == 0
    assert side["centre_m"][0] == pytest.approx(data["spacecraft"]["body_m"][0] / 2)
    # the body box leaves the wings out
    assert data["spacecraft"]["body_m"][1] < 1
    assert data["power_text"].startswith("# Fixture for the power tests")
