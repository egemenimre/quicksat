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
    plane_change_deltav,
)
from quicksat.mass.budget import MassBudget
from quicksat.utils.mission import Mission

CONFIG = """
propulsion:
  isp: 220 s
margin: 5
collision_avoidance:
  return_burn: true
"""

MISSION = "altitude: 500 km\ninclination: 97.4 deg\nduration: 7 yr\n"

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


LOSS_HEADER = HEADER.replace("recurring,", "recurring,loss_factor,")


def write_budget(tmp_path, rows=None, config=CONFIG, mission=MISSION, header=HEADER):
    """Writes a manoeuvre CSV, a config and a mission, and returns the three paths."""
    csv_path = tmp_path / "manoeuvres.csv"
    config_path = tmp_path / "config.yaml"
    mission_path = tmp_path / "mission.yaml"
    csv_path.write_text("\n".join([header, *(ROWS if rows is None else rows)]))
    config_path.write_text(config)
    mission_path.write_text(mission)
    return csv_path, config_path, mission_path


@pytest.fixture
def budget(tmp_path):
    return DeltaVBudget.from_csv(*write_budget(tmp_path))


# --- the closed forms --------------------------------------------------------


def test_hohmann_hop_of_200_m():
    """The pair of impulses for a 200 m raise from the sample orbit."""
    mission = Mission.from_yaml_text(MISSION)
    hop = hohmann_deltav(mission.radius, mission.radius + Q_(200, "m"))
    assert_allclose(hop, Q_(0.1107, "m/s"), atol=1e-4)


def test_hohmann_is_symmetric():
    """Going down costs what going up costs."""
    mission = Mission.from_yaml_text(MISSION)
    up = hohmann_deltav(mission.radius, mission.radius + Q_(10, "km"))
    down = hohmann_deltav(mission.radius + Q_(10, "km"), mission.radius)
    assert_allclose(up, down)


def test_deorbit_to_the_surface():
    mission = Mission.from_yaml_text(MISSION)
    from quicksat import R_EARTH

    assert_allclose(
        deorbit_deltav(mission.radius, R_EARTH), Q_(144.95, "m/s"), atol=0.01
    )


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
            tmp_path, mission=MISSION.replace("duration: 7 yr", "duration: 14 yr")
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
    mission = Mission.from_yaml_text(MISSION)
    one_way = hohmann_deltav(mission.radius, mission.radius + Q_(200, "m"))
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
    csv_path, config_path, mission_path = write_budget(tmp_path)
    csv_path.write_text("manoeuvre_id,manoeuvre_name\nx,X\n")
    with pytest.raises(ValueError, match="missing columns"):
        DeltaVBudget.from_csv(csv_path, config_path, mission_path)


def test_input_files_load(data_dir):
    budget = DeltaVBudget.from_csv(
        data_dir / "manoeuvres.csv",
        data_dir / "delta_v_config.yaml",
        data_dir / "mission.yaml",
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
    for column in ("row_type", "comments", "loss_factor"):
        assert column in report.data.columns
    assert "Comments" not in report.to_html()
    assert "Comments" in budget.tabulated_deltav(comments=True).to_html()


def test_report_shows_the_loss_factor_only_on_request(budget):
    """A column of ones is not worth the width until some row carries one."""
    assert "Loss factor" not in budget.tabulated_deltav().to_html()
    shown = budget.tabulated_deltav(loss_factor=True)
    assert "Loss factor" in shown.to_html()
    factors = shown.data.loc[shown.data["row_type"] == "manoeuvre", "loss_factor"]
    assert (factors == 1.0).all()


def test_report_loss_factor_reaches_the_rendered_table(tmp_path):
    row = "hop,Altitude hop,Operations,altitude_change,1 km,1,false,1.07,"
    budget = DeltaVBudget.from_csv(*write_budget(tmp_path, [row], header=LOSS_HEADER))
    html = budget.tabulated_deltav(loss_factor=True).to_html()
    assert "1.07" in html


def test_report_without_margin_stops_at_the_subtotal(budget):
    types = set(budget.tabulated_deltav(margin=False).data["row_type"])
    assert "margin" not in types and "total" not in types
    assert "subtotal" in types


# --- the loss factor ---------------------------------------------------------


def test_loss_factor_defaults_to_the_impulsive_ideal(budget):
    """The column is optional: a file without it is priced as an impulsive burn."""
    assert (budget.manoeuvre_table["loss_factor"] == 1.0).all()


def test_loss_factor_scales_the_manoeuvre(tmp_path):
    """3% of finite-burn loss costs 3% more delta-V, on that row alone."""
    rows = [
        "hop,Altitude hop,Operations,altitude_change,1 km,1,false,1.03,",
        "trim,Plane trim,Commissioning,inclination_change,0.05 deg,1,false,1.0,",
    ]
    budget = DeltaVBudget.from_csv(*write_budget(tmp_path, rows, header=LOSS_HEADER))
    ideal = hohmann_deltav(budget.mission.radius, budget.mission.radius + Q_(1, "km"))
    frame = budget.resolve().set_index("manoeuvre_id")
    assert_allclose(Q_(frame.loc["hop", "deltav_each"], "m/s"), ideal * 1.03)
    assert_allclose(
        Q_(frame.loc["trim", "deltav_each"], "m/s"),
        plane_change_deltav(budget.mission.velocity, Q_(0.05, "deg")),
    )


def test_loss_factor_applies_before_the_count(tmp_path):
    """A recurring row pays the loss on every occurrence, not once."""
    row = "cam,Collision avoidance,Operations,collision_avoidance,200 m,4,true,1.10,"
    budget = DeltaVBudget.from_csv(*write_budget(tmp_path, [row], header=LOSS_HEADER))
    frame = budget.resolve().iloc[0]
    assert frame.occurrences == pytest.approx(28.0)
    assert frame.deltav_total == pytest.approx(frame.deltav_each * 28.0)
    assert frame.deltav_each == pytest.approx(0.1107 * 2 * 1.10, abs=1e-4)


def test_loss_factor_below_one_is_rejected(tmp_path):
    """A burn cannot cost less than the impulsive ideal, so 0.97 is a typo."""
    row = "hop,Altitude hop,Operations,altitude_change,1 km,1,false,0.97,"
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        DeltaVBudget.from_csv(*write_budget(tmp_path, [row], header=LOSS_HEADER))


# --- the optional mass budget ------------------------------------------------


MASS_CONFIG = """
locations:
  Platform:
    system_margin: 20
    harness_fraction: 10
    harness_margin: 10
"""

MASS_CSV = """\
equipment_id,equipment_name,location,responsibility,subsystem,\
unit_mass,eqpt_margin,number_of_units,mass_class,comments
bus,Bus,Platform,Platform,Structure,400 kg,10,1,equipment,
fuel,Hydrazine,Platform,Platform,Propulsion,20 kg,0,1,propellant,
"""


@pytest.fixture
def mass_budget(tmp_path):
    """A spacecraft of its own, so the delta-V tests do not import the mass ones."""
    csv_path = tmp_path / "equipment.csv"
    config_path = tmp_path / "mass_config.yaml"
    csv_path.write_text(MASS_CSV)
    config_path.write_text(MASS_CONFIG)
    return MassBudget.from_csv(csv_path, config_path)


def test_propellant_mass_needs_a_dry_mass_from_somewhere(budget):
    """Unattached and unargued, it says so rather than guessing."""
    with pytest.raises(ValueError, match="no mass budget attached"):
        budget.propellant_mass()


def test_propellant_mass_falls_back_to_the_attached_budget(tmp_path, mass_budget):
    """No argument means the in-orbit mass with the tanks empty."""
    paths = write_budget(tmp_path)
    attached = DeltaVBudget.from_csv(*paths, mass_budget=mass_budget)
    loose = DeltaVBudget.from_csv(*paths)
    assert_allclose(
        attached.propellant_mass(),
        loose.propellant_mass(mass_budget.in_orbit_mass(propellant=0)),
    )


def test_an_explicit_dry_mass_overrides_the_attached_budget(tmp_path, mass_budget):
    """The what-if path: ask for another spacecraft without touching the file."""
    budget = DeltaVBudget.from_csv(*write_budget(tmp_path), mass_budget=mass_budget)
    assert budget.propellant_mass(Q_(600, "kg")) > budget.propellant_mass()


def test_the_mass_budget_is_not_required(tmp_path):
    """Every other query works without one, so the coupling stays optional."""
    budget = DeltaVBudget.from_csv(*write_budget(tmp_path))
    assert budget.mass_budget is None
    assert budget.total_deltav().magnitude > 0
    assert not budget.by_phase().empty
