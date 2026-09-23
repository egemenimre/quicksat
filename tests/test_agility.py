# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the attitude agility budget.

The workbook targets come from the source `Agility (Roll)` tab, independently
recomputed from the inputs and flown as an envelope case against a 475 kg
spacecraft handed in directly, so they stay pinned whatever the mass budget says.

    inertia, 475 kg box 1.5 x 1.5 x 2.0 m, factor 1.07     264.7 kg*m**2
    projection, cos(26.5 deg) * cos(45 deg)                0.633
    axis momentum / torque                                 3.372 N*m*s, 0.380 N*m
    yaw momentum                                           2.38 N*m*s
    max rate / acceleration / crossover        0.730 deg/s, 0.001434 rad/s**2, 6.48 deg
    40 deg + 20 s settling against a 113 s target duration      83.7 s, 35.0% margin
    largest slew inside that target duration                    61.4 deg
"""

import pytest
from pint.testing import assert_allclose

from quicksat import Q_
from quicksat.agility.budget import AgilityBudget, AgilityConfig, Axis, Profile
from quicksat.mass.budget import MassBudget
from quicksat.utils.orbit import Orbit

CONFIG = """
inertia_cases:
  workbook:
    body:
      x: 1.5 m
      y: 1.5 m
      z: 2.0 m
    appendage_factor:
      roll: 1.07
      pitch: 1.07
    propellant: 100 %
  workbook_eol:
    body:
      x: 1.5 m
      y: 1.5 m
      z: 2.0 m
    appendage_factor:
      roll: 1.07
      pitch: 1.07
    propellant: 0 %
  stated:
    inertia:
      roll: 300.0 kg*m**2
      pitch: 340.0 kg*m**2
wheels:
  count: 4
  elevation: 26.5 deg
  momentum: 4.0 N*m*s
  torque: 0.2 N*m
  momentum_use_factor: 33.3 %
  torque_derating: 75 %
settling_time: 20 s
"""

ORBIT = "altitude: 500 km\ninclination: 97.4 deg\n"

MASS_CONFIG = (
    "locations:\n  Platform:\n    system_margin: 0\n"
    "    harness_fraction: 0\n    harness_margin: 0\n"
)

MASS_CSV = """\
equipment_id,equipment_name,location,responsibility,subsystem,\
unit_mass,eqpt_margin,number_of_units,mass_class,comments
bus,Bus,Platform,Platform,Structure,455 kg,0,1,equipment,
fuel,Hydrazine,Platform,Platform,Propulsion,20 kg,0,1,propellant,
"""

WORKBOOK_MASS = Q_(475, "kg")
"""The source tab's spacecraft, handed in directly so the workbook figures stay
pinned to it while the sample notebooks track our own mass budget."""

TARGET_DURATION = Q_(113, "s")
"""What the source tab's operation allows. An argument, not config: how long a
manoeuvre may take is asked of a spacecraft, not a property of one."""

# angle -> (nominal slew time, one-wheel-failed slew time), in seconds
SLEW_TIMES = {
    5: (15.6, 22.6),
    10: (22.6, 36.3),
    15: (29.4, 50.0),
    20: (36.3, 63.7),
    40: (63.7, 118.5),
    45: (70.5, 132.2),
    60: (91.1, 173.3),
    90: (132.2, 255.5),
}


@pytest.fixture
def config():
    return AgilityConfig.from_yaml_text(CONFIG)


@pytest.fixture
def orbit():
    return Orbit.from_yaml_text(ORBIT)


@pytest.fixture
def budget(config, orbit):
    return AgilityBudget(config, orbit, Axis.ROLL, "workbook", mass=WORKBOOK_MASS)


@pytest.fixture
def bus(tmp_path):
    """A spacecraft of its own, so these tests do not lean on the sample files."""
    csv_path = tmp_path / "equipment.csv"
    config_path = tmp_path / "mass_config.yaml"
    csv_path.write_text(MASS_CSV)
    config_path.write_text(MASS_CONFIG)
    return MassBudget.from_csv(csv_path, config_path)


# --- the assembly ------------------------------------------------------------


def test_inertia_of_the_box_with_its_appendage_uplift(budget):
    assert_allclose(budget.inertia, Q_(264.7, "kg * m**2"), atol=0.1)


def test_projection_onto_an_in_plane_axis(budget):
    """Into the pyramid base plane, then onto roll within it."""
    assert budget.projection.magnitude == pytest.approx(0.633, abs=1e-3)


def test_axis_capability(budget):
    assert_allclose(budget.axis_momentum(), Q_(3.372, "N * m * s"), atol=1e-3)
    assert_allclose(budget.axis_torque(), Q_(0.380, "N * m"), atol=1e-3)


def test_yaw_is_the_weak_axis(budget):
    """Reported rather than slewed, but it is what a yaw manoeuvre lives within."""
    assert_allclose(budget.yaw_momentum, Q_(2.38, "N * m * s"), atol=0.01)
    assert budget.yaw_momentum < budget.axis_momentum()


def test_derived_limits(budget):
    assert_allclose(budget.max_rate(), Q_(0.730, "deg / s"), atol=1e-3)
    assert_allclose(
        budget.max_acceleration().to("rad / s**2"),
        Q_(0.001434, "rad / s**2"),
        atol=1e-6,
    )
    assert_allclose(budget.crossover_angle(), Q_(6.48, "deg"), atol=0.01)


# --- the slew profile --------------------------------------------------------


@pytest.mark.parametrize("angle, expected", [(a, t[0]) for a, t in SLEW_TIMES.items()])
def test_slew_times(budget, angle, expected):
    assert_allclose(budget.slew_time(Q_(angle, "deg")), Q_(expected, "s"), atol=0.05)


@pytest.mark.parametrize("angle, expected", [(a, t[1]) for a, t in SLEW_TIMES.items()])
def test_slew_times_with_one_wheel_failed(budget, angle, expected):
    """Halved momentum and torque about the same axis, not a different mounting."""
    time = budget.slew_time(Q_(angle, "deg"), degraded=True)
    assert_allclose(time, Q_(expected, "s"), atol=0.05)


def test_the_profile_flips_at_the_crossover(budget):
    """The model's one qualitative output: which limit binds."""
    crossover = budget.crossover_angle()
    assert budget.profile(crossover * 0.99) is Profile.TRIANGULAR
    assert budget.profile(crossover * 1.01) is Profile.TRAPEZOIDAL


def test_momentum_is_fully_used_past_the_crossover(budget):
    """Which is what momentum limited means."""
    used = budget.momentum_used(Q_(5, "deg")).magnitude
    assert used == pytest.approx(0.878, abs=1e-3)
    for angle in (10, 40, 90):
        assert budget.momentum_used(Q_(angle, "deg")).magnitude == pytest.approx(1.0)


def test_a_degraded_slew_is_never_faster(budget):
    for angle in SLEW_TIMES:
        angle = Q_(angle, "deg")
        assert budget.slew_time(angle, degraded=True) > budget.slew_time(angle)


# --- the requirement check, against a target duration supplied at the call --


def test_the_requirement_case(budget):
    """40 degrees plus settling, against the operation's target duration."""
    angle = Q_(40, "deg")
    assert_allclose(budget.total_time(angle), Q_(83.7, "s"), atol=0.05)
    margin = budget.time_margin(angle, TARGET_DURATION).magnitude
    assert margin == pytest.approx(0.350, abs=1e-3)


def test_the_largest_slew_that_fits(budget):
    assert_allclose(
        budget.achievable_angle(TARGET_DURATION), Q_(61.4, "deg"), atol=0.05
    )


def test_achievable_angle_inverts_the_slew_time(budget):
    """The inverse solve and the forward solve have to agree."""
    achievable = budget.achievable_angle(TARGET_DURATION)
    assert_allclose(budget.total_time(achievable), TARGET_DURATION, atol=1e-6)


def test_a_tighter_target_allows_a_smaller_slew(budget):
    """The target is an argument, so the same spacecraft answers both ways."""
    assert budget.achievable_angle(Q_(60, "s")) < budget.achievable_angle(
        TARGET_DURATION
    )
    assert budget.time_margin(Q_(40, "deg"), Q_(60, "s")).magnitude < 0


def test_ground_track_ties_the_slew_to_the_orbit(budget):
    """A slew time means something because it is swath given up."""
    assert_allclose(budget.ground_distance(TARGET_DURATION), Q_(797.7, "km"), atol=0.1)


# --- the inertia cases -------------------------------------------------------


def test_a_stated_case_gives_its_inertia_verbatim(config, orbit):
    """And needs no mass at all: inertia is the only route mass takes in."""
    budget = AgilityBudget(config, orbit, Axis.ROLL, "stated")
    assert_allclose(budget.inertia, Q_(300.0, "kg * m**2"))
    assert budget.mass_budget is None
    assert budget.slew_time(Q_(40, "deg")).magnitude > 0


def test_a_stated_case_is_per_axis(config, orbit):
    pitch = AgilityBudget(config, orbit, Axis.PITCH, "stated")
    assert_allclose(pitch.inertia, Q_(340.0, "kg * m**2"))


def test_an_envelope_case_needs_a_mass_from_somewhere(config, orbit):
    budget = AgilityBudget(config, orbit, Axis.ROLL, "workbook")
    with pytest.raises(ValueError, match="needs a mass"):
        _ = budget.inertia


def test_an_envelope_case_reads_the_budget_at_its_own_propellant(config, orbit, bus):
    """Tanks empty over the mission, so the spacecraft grows more agile with age."""
    bol = AgilityBudget(config, orbit, Axis.ROLL, "workbook", mass_budget=bus)
    eol = AgilityBudget(config, orbit, Axis.ROLL, "workbook_eol", mass_budget=bus)
    assert bol.mass > eol.mass
    assert bol.inertia > eol.inertia
    assert bol.slew_time(Q_(40, "deg")) > eol.slew_time(Q_(40, "deg"))
    assert bol.achievable_angle(TARGET_DURATION) < eol.achievable_angle(TARGET_DURATION)


def test_an_explicit_mass_wins_over_the_attached_budget(config, orbit, bus):
    """The what-if path, and it overrides rather than raising."""
    budget = AgilityBudget(
        config, orbit, Axis.ROLL, "workbook", mass_budget=bus, mass=WORKBOOK_MASS
    )
    assert_allclose(budget.mass, WORKBOOK_MASS)
    assert_allclose(budget.inertia, Q_(264.7, "kg * m**2"), atol=0.1)


def test_cases_give_different_answers(config, orbit):
    """Which is the whole point of naming more than one."""
    stated = AgilityBudget(config, orbit, Axis.ROLL, "stated")
    envelope = AgilityBudget(config, orbit, Axis.ROLL, "workbook", mass=WORKBOOK_MASS)
    angle = Q_(40, "deg")
    assert stated.slew_time(angle) != envelope.slew_time(angle)


def test_an_unknown_case_is_an_error(config, orbit):
    """Rather than a silent fallback answering for a spacecraft nobody asked for."""
    with pytest.raises(KeyError, match="No inertia case named 'typo'"):
        AgilityBudget(config, orbit, Axis.ROLL, "typo")


def test_the_config_carries_no_mass(config):
    """The mass budget owns it. A config that states one is a second source."""
    assert "mass" not in CONFIG
    for case in config.inertia_cases.values():
        assert not hasattr(case, "mass")


# --- the axes ----------------------------------------------------------------


def test_pitch_runs_the_same_machinery(budget, config, orbit):
    """Same wheels, same plane; only the inertia can differ."""
    pitch = AgilityBudget(config, orbit, Axis.PITCH, "workbook", mass=WORKBOOK_MASS)
    assert pitch.projection == budget.projection
    assert pitch.axis_momentum() == budget.axis_momentum()


def test_a_heavier_axis_slews_more_slowly(orbit):
    """Raising the pitch appendage factor must show up as a slower pitch slew."""
    config = AgilityConfig.from_yaml_text(CONFIG.replace("pitch: 1.07", "pitch: 1.30"))
    roll = AgilityBudget(config, orbit, Axis.ROLL, "workbook", mass=WORKBOOK_MASS)
    pitch = AgilityBudget(config, orbit, Axis.PITCH, "workbook", mass=WORKBOOK_MASS)
    assert pitch.inertia > roll.inertia
    assert pitch.slew_time(Q_(40, "deg")) > roll.slew_time(Q_(40, "deg"))


# --- the table and the report ------------------------------------------------


def test_slew_table_covers_the_default_angles(budget):
    frame = budget.slew_table()
    assert list(frame["angle"]) == [5, 10, 15, 20, 40, 45, 60, 90]
    assert frame["slew_time"].is_monotonic_increasing


def test_report_marks_what_does_not_fit(budget):
    report = budget.tabulated_agility(target_duration=TARGET_DURATION)
    verdicts = dict(zip(report.data["angle"], report.data["verdict"], strict=True))
    assert verdicts[40] == "PASS"
    assert verdicts[90] == "FAILS"
    assert "Momentum used" in report.to_html()


def test_report_omits_the_check_without_a_target(budget):
    """There is nothing to check against, so the columns are left out entirely."""
    report = budget.tabulated_agility()
    assert "verdict" not in report.data.columns
    assert "margin" not in report.data.columns
    assert "Slew [s]" in report.to_html()


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ("momentum: 4.0 N*m*s", "momentum: 4.0 kg", "angular momentum dimensions"),
        ("torque: 0.2 N*m", "torque: 0.2 m", "torque dimensions"),
        ("count: 4", "count: 0", "greater than or equal to 1"),
        ("settling_time: 20 s", "settling_time: -5 s", "must not be negative"),
    ],
)
def test_validation_failures(old, new, expected):
    with pytest.raises(ValueError, match=expected):
        AgilityConfig.from_yaml_text(CONFIG.replace(old, new))


def test_a_case_cannot_be_both_shapes():
    """A stated inertia does not follow the mass, so the two would disagree."""
    both = CONFIG.replace(
        "  stated:\n    inertia:",
        "  stated:\n    body:\n      x: 1 m\n      y: 1 m\n      z: 1 m\n"
        "    appendage_factor:\n      roll: 1.0\n      pitch: 1.0\n    inertia:",
    )
    with pytest.raises(ValueError, match="one or the other"):
        AgilityConfig.from_yaml_text(both)


def test_a_case_cannot_be_neither_shape():
    """And the message names what was found, not just that a union failed."""
    neither = CONFIG.replace(
        "    appendage_factor:\n      roll: 1.07\n      pitch: 1.07\n", "", 1
    )
    with pytest.raises(ValueError, match=r"missing \['appendage_factor'\]"):
        AgilityConfig.from_yaml_text(neither)


def test_config_missing_file():
    with pytest.raises(FileNotFoundError):
        AgilityConfig.from_yaml_file("no/such/agility.yaml")


def test_input_files_load(data_dir):
    budget = AgilityBudget.from_yaml_file(
        data_dir / "agility_config.yaml",
        data_dir / "orbit.yaml",
        Axis.ROLL,
        "measured_bol",
    )
    assert_allclose(budget.inertia, Q_(264.7, "kg * m**2"), atol=0.1)
