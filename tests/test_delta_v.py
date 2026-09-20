# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the delta-V budget.

The fixture flies from the sample 500 km orbit, where the circular velocity is
7.6126 km/s. Hand-checked references:

    a 200 m Hohmann hop            0.1107 m/s for the pair of impulses
    deorbit to a 0 km perigee      144.95 m/s
    deorbit to a 250 km perigee     70.78 m/s
    80 m/s at Isp 220 s, 450 kg dry   17.00 kg of propellant
"""

import math

import pytest
from pint.testing import assert_allclose

from quicksat import Q_
from quicksat.delta_v.budget import (
    DeltaVBudget,
    DeltaVConfig,
    deorbit_deltav,
    hohmann_deltav,
)
from quicksat.utils.orbit import Orbit

CONFIG = """
mission:
  duration: 7 yr
propulsion:
  isp: 220 s
margin: 5
collision_avoidance:
  return_burn: true
"""

ORBIT = "altitude: 500 km\ninclination: 97.4 deg\n"

HEADER = (
    "manoeuvre_id,manoeuvre_name,phase,manoeuvre_type,value,count,recurring,comments"
)

ROWS = [
    "hop,Altitude hop,Operations,altitude_change,1 km,1,false,",
    "cam,Collision avoidance,Operations,collision_avoidance,200 m,4,true,",
    "trim,Plane trim,Commissioning,inclination_change,0.05 deg,1,false,",
    "eol,Deorbit,Disposal,deorbit,0 km,1,false,",
    "phasing,Phasing,Commissioning,given,8 m/s,1,false,",
]


def write_budget(tmp_path, rows=None, config=CONFIG, orbit=ORBIT):
    """Writes a manoeuvre CSV, a config and an orbit, and returns the three paths."""
    csv_path = tmp_path / "manoeuvres.csv"
    config_path = tmp_path / "config.yaml"
    orbit_path = tmp_path / "orbit.yaml"
    csv_path.write_text("\n".join([HEADER, *(ROWS if rows is None else rows)]))
    config_path.write_text(config)
    orbit_path.write_text(orbit)
    return csv_path, config_path, orbit_path


@pytest.fixture
def budget(tmp_path):
    return DeltaVBudget.from_csv(*write_budget(tmp_path))


# --- the closed forms --------------------------------------------------------


def test_hohmann_hop_of_200_m():
    """The pair of impulses for a 200 m raise from the sample orbit."""
    orbit = Orbit.from_yaml_text(ORBIT)
    hop = hohmann_deltav(orbit.radius, orbit.radius + Q_(200, "m"))
    assert_allclose(hop, Q_(0.1107, "m/s"), atol=1e-4)


def test_hohmann_is_symmetric():
    """Going down costs what going up costs."""
    orbit = Orbit.from_yaml_text(ORBIT)
    up = hohmann_deltav(orbit.radius, orbit.radius + Q_(10, "km"))
    down = hohmann_deltav(orbit.radius + Q_(10, "km"), orbit.radius)
    assert_allclose(up, down)


def test_deorbit_to_the_surface():
    orbit = Orbit.from_yaml_text(ORBIT)
    from quicksat import R_EARTH

    assert_allclose(deorbit_deltav(orbit.radius, R_EARTH), Q_(144.95, "m/s"), atol=0.01)


def test_plane_change_costs_more_than_the_same_altitude_change(budget):
    """A degree of plane change is expensive; a kilometre of altitude is not."""
    frame = budget.resolve().set_index("manoeuvre_id")
    assert frame.loc["trim", "deltav_each"] > frame.loc["hop", "deltav_each"]


# --- counts and the mission duration -----------------------------------------


def test_recurring_rows_scale_with_the_mission(budget):
    """4 a year over 7 years is 28; a one-off stays 1."""
    frame = budget.resolve().set_index("manoeuvre_id")
    assert frame.loc["cam", "occurrences"] == pytest.approx(28.0)
    assert frame.loc["hop", "occurrences"] == pytest.approx(1.0)


def test_a_longer_mission_costs_more_only_through_the_recurring_rows(tmp_path):
    seven = DeltaVBudget.from_csv(*write_budget(tmp_path))
    fourteen = DeltaVBudget.from_csv(
        *write_budget(
            tmp_path, config=CONFIG.replace("duration: 7 yr", "duration: 14 yr")
        )
    )
    recurring = seven.resolve().set_index("manoeuvre_id").loc["cam", "deltav_total"]
    assert_allclose(
        fourteen.total_deltav(),
        seven.total_deltav() + Q_(recurring * 1.05, "m/s"),
    )


# --- the margin -------------------------------------------------------------


def test_margin_applies_once_to_the_total(budget):
    assert_allclose(
        budget.total_deltav(margin=True),
        budget.total_deltav(margin=False) * 1.05,
    )


@pytest.mark.parametrize("margin", [True, False])
def test_groupings_reconcile(budget, margin):
    """Both axes sum to the grand total, with or without the margin."""
    expected = budget.total_deltav(margin)
    assert_allclose(Q_(budget.by_phase(margin)["deltav"].sum(), "m/s"), expected)
    assert_allclose(Q_(budget.by_type(margin)["deltav"].sum(), "m/s"), expected)


# --- the collision avoidance policy ------------------------------------------


def test_return_burn_doubles_only_the_avoidance_line(tmp_path):
    both = DeltaVBudget.from_csv(*write_budget(tmp_path))
    one_way = DeltaVBudget.from_csv(
        *write_budget(
            tmp_path, config=CONFIG.replace("return_burn: true", "return_burn: false")
        )
    )
    frames = [b.resolve().set_index("manoeuvre_id") for b in (both, one_way)]

    assert frames[0].loc["cam", "deltav_each"] == pytest.approx(
        2 * frames[1].loc["cam", "deltav_each"]
    )
    for other in ("hop", "trim", "eol", "phasing"):
        assert frames[0].loc[other, "deltav_each"] == pytest.approx(
            frames[1].loc[other, "deltav_each"]
        )


def test_an_avoidance_hop_is_two_transfers(budget):
    """With a return burn it is exactly twice the one-way Hohmann."""
    orbit = Orbit.from_yaml_text(ORBIT)
    one_way = hohmann_deltav(orbit.radius, orbit.radius + Q_(200, "m"))
    frame = budget.resolve().set_index("manoeuvre_id")
    assert_allclose(Q_(frame.loc["cam", "deltav_each"], "m/s"), 2 * one_way)


# --- the rocket equation -----------------------------------------------------


def test_propellant_from_dry_mass(tmp_path):
    """
    80 m/s at Isp 220 s from 450 kg dry needs 17.00 kg.

    The argument is the dry mass, so it is the final mass of the burn and the
    propellant is `m_dry * (exp(dv/ve) - 1)`.
    """
    rows = ["phasing,Phasing,Operations,given,80 m/s,1,false,"]
    budget = DeltaVBudget.from_csv(
        *write_budget(tmp_path, rows, config=CONFIG.replace("margin: 5", "margin: 0"))
    )
    propellant = budget.propellant_mass(Q_(450, "kg"))
    assert_allclose(propellant, Q_(17.00, "kg"), atol=0.01)


def test_propellant_satisfies_the_rocket_equation(budget):
    """Wet over dry is exp(dv/ve), which is the equation the figure came from."""
    dry = Q_(450, "kg")
    propellant = budget.propellant_mass(dry)
    exhaust = budget.config.propulsion.isp * Q_(1, "standard_gravity")
    expected = math.exp((budget.total_deltav() / exhaust).to("dimensionless").magnitude)
    assert_allclose((dry + propellant) / dry, Q_(expected, "dimensionless"))


def test_more_deltav_needs_more_propellant(budget):
    dry = Q_(450, "kg")
    assert budget.propellant_mass(dry, margin=True) > budget.propellant_mass(
        dry, margin=False
    )


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "row, expected",
    [
        ("x,X,Ops,given,200 m,1,false,", "needs a velocity"),
        ("x,X,Ops,altitude_change,8 m/s,1,false,", "needs a length"),
        ("x,X,Ops,inclination_change,5 km,1,false,", "needs an angle"),
        ("x,X,Ops,deorbit,3 kg,1,false,", "needs a length"),
        ("a b,X,Ops,given,8 m/s,1,false,", "manoeuvre_id"),
        ("x,X,Ops,given,8 m/s,-1,false,", "greater than or equal to 0"),
        ("x,X,Ops,teleport,8 m/s,1,false,", "manoeuvre_type"),
    ],
)
def test_validation_failures(tmp_path, row, expected):
    with pytest.raises(ValueError, match=expected):
        DeltaVBudget.from_csv(*write_budget(tmp_path, [row]))


def test_missing_column(tmp_path):
    csv_path, config_path, orbit_path = write_budget(tmp_path)
    csv_path.write_text("manoeuvre_id,manoeuvre_name\nx,X\n")
    with pytest.raises(ValueError, match="missing columns"):
        DeltaVBudget.from_csv(csv_path, config_path, orbit_path)


def test_input_files_load(data_dir):
    budget = DeltaVBudget.from_csv(
        data_dir / "manoeuvres.csv",
        data_dir / "delta_v_config.yaml",
        data_dir / "orbit.yaml",
    )
    assert_allclose(budget.total_deltav(), Q_(116.5, "m/s"), atol=0.5)


def test_config_missing_file():
    with pytest.raises(FileNotFoundError):
        DeltaVConfig.from_yaml_file("no/such/config.yaml")


def test_manoeuvre_table_is_a_copy(budget):
    """The validated list, handed out so nothing downstream writes back."""
    frame = budget.manoeuvre_table
    assert list(frame["manoeuvre_id"]) == ["hop", "cam", "trim", "eol", "phasing"]

    frame.loc[0, "count"] = 999
    assert budget.manoeuvre_table.loc[0, "count"] == 1


# --- the report --------------------------------------------------------------


def test_report_totals_match_the_budget(budget):
    frame = budget.tabulated_deltav().data
    total = frame.loc[frame["row_type"] == "total", "deltav"].iloc[0]
    subtotal = frame.loc[frame["row_type"] == "subtotal", "deltav"].iloc[0]

    assert_allclose(Q_(total, "m/s"), budget.total_deltav(margin=True))
    assert_allclose(Q_(subtotal, "m/s"), budget.total_deltav(margin=False))


def test_report_phase_subtotals_sum_to_the_budget(budget):
    frame = budget.tabulated_deltav().data
    phases = frame.loc[frame["row_type"] == "phase_subtotal", "deltav"]
    assert_allclose(Q_(phases.sum(), "m/s"), budget.total_deltav(margin=False))


def test_report_hides_columns_without_dropping_them(budget):
    report = budget.tabulated_deltav()
    for column in ("row_type", "comments"):
        assert column in report.data.columns
    assert "Comments" not in report.to_html()
    assert "Comments" in budget.tabulated_deltav(comments=True).to_html()


def test_report_without_margin_stops_at_the_subtotal(budget):
    types = set(budget.tabulated_deltav(margin=False).data["row_type"])
    assert "margin" not in types and "total" not in types
    assert "subtotal" in types
