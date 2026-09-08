# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the mass budget.

The fixture is deliberately small enough to check by hand:

    box_a   Platform  10 kg  100% margin   -> cbe 10, mev 20
    box_b   Payload   20 kg   50% margin   -> cbe 20, mev 30
    fuel    Platform   5 kg  propellant    -> cbe  5, mev  5 (never margined)
    lv_ring Launcher   4 kg    0% margin   -> cbe  4, mev  4

    Platform harness = 10% of Platform equipment CBE (10 kg) = 1.0 kg,
                       +10% harness margin              -> mev 1.1
    System margins: Platform 20%, Payload 0%, Launcher 0% (reserved default)

    on ground, wet = 24 + 1.32 + 30 + 5 + 4 = 64.32 kg
    on ground, dry =                          59.32 kg
    in orbit,  wet =                          60.32 kg
    in orbit,  dry =                          55.32 kg
"""

import pytest

from quicksat.mass.budget import MassBudget, MassCase

CONFIG = """
locations:
  Platform:
    system_margin: 20
    harness_fraction: 10
    harness_margin: 10
  Payload:
    system_margin: 0
    harness_fraction: 0
    harness_margin: 0
"""

HEADER = (
    "equipment_id,equipment_name,location,responsibility,subsystem,"
    "unit_mass,equipment_margin,number_of_units,mass_class,comments"
)

ROWS = [
    "box_a,Box A,Platform,Platform,ADCS,10 kg,100,1,equipment,",
    "box_b,Box B,Payload,Payload,Optics,20 kg,50,1,equipment,",
    "fuel,Hydrazine,Platform,Platform,Propulsion,5 kg,0,1,propellant,",
    "lv_ring,Adapter ring,Launcher,Launcher,Structure,4 kg,0,1,equipment,",
]


def write_budget(tmp_path, rows=None, config=CONFIG):
    """Writes a CSV/YAML pair to `tmp_path` and returns the two paths."""
    csv_path = tmp_path / "equipment.csv"
    config_path = tmp_path / "config.yaml"
    csv_path.write_text("\n".join([HEADER, *(ROWS if rows is None else rows)]))
    config_path.write_text(config)
    return csv_path, config_path


@pytest.fixture
def budget(tmp_path):
    return MassBudget.from_csv(*write_budget(tmp_path))


@pytest.mark.parametrize(
    "case, with_propellant, expected",
    [
        (MassCase.ON_GROUND, True, 64.32),
        (MassCase.ON_GROUND, False, 59.32),
        (MassCase.IN_ORBIT, True, 60.32),
        (MassCase.IN_ORBIT, False, 55.32),
    ],
)
def test_four_mass_cases(budget, case, with_propellant, expected):
    total = budget.total(case=case, with_propellant=with_propellant)
    assert total.to("kg").magnitude == pytest.approx(expected)


def test_launcher_hardware_dropped_in_orbit(budget):
    """Launch mass less in-orbit mass is exactly the launcher-side hardware."""
    on_ground = budget.total(case=MassCase.ON_GROUND).to("kg").magnitude
    in_orbit = budget.total(case=MassCase.IN_ORBIT).to("kg").magnitude
    assert on_ground - in_orbit == pytest.approx(4.0)


def test_propellant_is_never_margined(budget):
    """Propellant skips the equipment margin and the system margin alike."""
    frame = budget.resolve(case=MassCase.IN_ORBIT, with_propellant=True)
    fuel = frame[frame["equipment_id"] == "fuel"].iloc[0]
    assert fuel["cbe_kg"] == pytest.approx(5.0)
    assert fuel["mev_kg"] == pytest.approx(5.0)
    assert fuel["total_kg"] == pytest.approx(5.0)


def test_harness_uses_cbe_and_excludes_propellant(budget):
    """
    Harness is 10% of the 10 kg Platform equipment CBE.

    It would be 2.0 kg if the margined mass were used, and 1.5 kg if the 5 kg of
    propellant at the same location counted towards the base.
    """
    frame = budget.equipment
    harness = frame[frame["subsystem"] == "Harness"]
    assert len(harness) == 1
    assert harness.iloc[0]["location"] == "Platform"
    assert harness.iloc[0]["cbe_kg"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    "case, with_propellant",
    [
        (MassCase.ON_GROUND, True),
        (MassCase.ON_GROUND, False),
        (MassCase.IN_ORBIT, True),
        (MassCase.IN_ORBIT, False),
    ],
)
def test_harness_identical_across_cases(budget, case, with_propellant):
    frame = budget.resolve(case=case, with_propellant=with_propellant)
    harness = frame[frame["subsystem"] == "Harness"]
    assert harness.iloc[0]["total_kg"] == pytest.approx(1.32)


@pytest.mark.parametrize(
    "case, with_propellant",
    [
        (MassCase.ON_GROUND, True),
        (MassCase.ON_GROUND, False),
        (MassCase.IN_ORBIT, True),
        (MassCase.IN_ORBIT, False),
    ],
)
def test_groupings_reconcile(budget, case, with_propellant):
    """All three axes must sum to the same grand total, in every case."""
    kwargs = {"case": case, "with_propellant": with_propellant}
    expected = budget.total(**kwargs).to("kg").magnitude
    for view in (
        budget.by_location(**kwargs),
        budget.by_responsibility(**kwargs),
        budget.by_subsystem(**kwargs),
    ):
        assert view["total"].sum() == pytest.approx(expected)


def test_harness_appears_on_every_axis(budget):
    """The synthetic row is tagged so it shows as its own line in each view."""
    assert "Harness" in budget.by_subsystem().index
    assert "Harness" in budget.by_responsibility().index
    assert "Platform" in budget.by_location().index


def test_units_are_converted(tmp_path):
    """A mass entered in grams lands in the frame as kilograms."""
    rows = ["imu,IMU,Payload,Payload,ADCS,750 g,0,2,equipment,"]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert budget.total().to("kg").magnitude == pytest.approx(1.5)


def test_zero_units_contributes_nothing(tmp_path):
    rows = [
        "box_b,Box B,Payload,Payload,Optics,20 kg,50,1,equipment,",
        "spare,Spare,Payload,Payload,Optics,99 kg,0,0,equipment,",
    ]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert budget.total().to("kg").magnitude == pytest.approx(30.0)


def test_blank_mass_class_defaults_to_equipment(tmp_path):
    rows = ["box_b,Box B,Payload,Payload,Optics,20 kg,50,1,,"]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert budget.total().to("kg").magnitude == pytest.approx(30.0)


@pytest.mark.parametrize(
    "row, expected",
    [
        (
            "star tracker,Box,Payload,Payload,ADCS,1 kg,0,1,equipment,",
            "equipment_id",
        ),
        ("box,Box,Payload,Payload,ADCS,100 W,0,1,equipment,", "mass dimensions"),
        ("box,Box,Payload,Payload,ADCS,1 kg,-5,1,equipment,", "equipment_margin"),
        ("box,Box,Payload,Payload,ADCS,1 kg,0,-1,equipment,", "number_of_units"),
        ("box,Box,Payload,Payload,ADCS,1 kg,0,1,ballast,", "mass_class"),
        ("box,Box,Deck_A,Payload,ADCS,1 kg,0,1,equipment,", "Deck_A"),
    ],
)
def test_validation_failures(tmp_path, row, expected):
    with pytest.raises(ValueError, match=expected):
        MassBudget.from_csv(*write_budget(tmp_path, [row]))


def test_duplicate_id_within_location_rejected(tmp_path):
    rows = [
        "box,Box,Payload,Payload,ADCS,1 kg,0,1,equipment,",
        "box,Box again,Payload,Payload,ADCS,2 kg,0,1,equipment,",
    ]
    with pytest.raises(ValueError, match="Duplicate"):
        MassBudget.from_csv(*write_budget(tmp_path, rows))


def test_same_id_across_locations_allowed(tmp_path):
    rows = [
        "box,Box,Payload,Payload,ADCS,1 kg,0,1,equipment,",
        "box,Box,Platform,Platform,ADCS,2 kg,0,1,equipment,",
    ]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert len(budget.equipment[budget.equipment["equipment_id"] == "box"]) == 2
