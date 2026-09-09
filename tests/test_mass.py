# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the mass budget.

The fixture is deliberately small enough to check by hand:

    box_a   Platform  10 kg  100% margin   -> mass 10, with margin 20
    box_b   Payload   20 kg   50% margin   -> mass 20, with margin 30
    fuel    Platform   5 kg  propellant    -> mass  5, never margined
    lv_ring Launcher   4 kg    0% margin   -> mass  4, with margin  4

    Platform harness = 10% of Platform equipment mass (10 kg) = 1.0 kg,
                       +10% harness margin           -> with margin 1.1
    System margins: Platform 20%, Payload 0%, Launcher 0% (reserved default)

    in orbit,  wet = 24 + 1.32 + 30 + 5     = 60.32 kg
    in orbit,  dry =                          55.32 kg
    on ground, wet =                 + 4    = 64.32 kg
    on ground, dry =                          59.32 kg
"""

import itertools

import pytest

from quicksat.mass.budget import MassBudget

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

ALL_FLAGS = [
    dict(
        zip(("wet", "sys_margin", "eqpt_margin", "in_orbit"), combination, strict=True)
    )
    for combination in itertools.product([True, False], repeat=4)
]


def write_budget(tmp_path, rows=None, config=CONFIG):
    """Writes a CSV/YAML pair to `tmp_path` and returns the two paths."""
    csv_path = tmp_path / "equipment.csv"
    config_path = tmp_path / "config.yaml"
    csv_path.write_text("\n".join([HEADER, *(ROWS if rows is None else rows)]))
    config_path.write_text(config)
    return csv_path, config_path


def kg(quantity):
    return quantity.to("kg").magnitude


@pytest.fixture
def budget(tmp_path):
    return MassBudget.from_csv(*write_budget(tmp_path))


# --- the four mass cases -------------------------------------------------------


@pytest.mark.parametrize(
    "in_orbit, wet, expected",
    [
        (False, True, 64.32),
        (False, False, 59.32),
        (True, True, 60.32),
        (True, False, 55.32),
    ],
)
def test_four_mass_cases(budget, in_orbit, wet, expected):
    assert kg(budget.total_mass(in_orbit=in_orbit, wet=wet)) == pytest.approx(expected)


def test_case_presets_match_the_generic_method(budget):
    assert budget.in_orbit_mass() == budget.total_mass(in_orbit=True)
    assert budget.on_ground_mass() == budget.total_mass(in_orbit=False)
    assert budget.in_orbit_mass(wet=False) == budget.total_mass(
        in_orbit=True, wet=False
    )


def test_launcher_hardware_dropped_in_orbit(budget):
    """On-ground less in-orbit mass is exactly the launcher-side hardware."""
    assert kg(budget.on_ground_mass()) - kg(budget.in_orbit_mass()) == pytest.approx(
        4.0
    )


# --- the margin flags ----------------------------------------------------------


@pytest.mark.parametrize(
    "sys_margin, eqpt_margin, expected",
    [
        (True, True, 60.32),  # 24 + 1.32 + 30 + 5
        (True, False, 38.20),  # 12 + 1.20 + 20 + 5
        (False, True, 56.10),  # 20 + 1.10 + 30 + 5
        (False, False, 36.00),  # 10 + 1.00 + 20 + 5
    ],
)
def test_margin_flags(budget, sys_margin, eqpt_margin, expected):
    """Each margin layer can be switched off independently, including sys-only."""
    total = budget.total_mass(sys_margin=sys_margin, eqpt_margin=eqpt_margin)
    assert kg(total) == pytest.approx(expected)


def test_propellant_is_never_margined(budget):
    """Propellant ignores both margin flags."""
    for flags in ALL_FLAGS:
        if not flags["wet"]:
            continue
        frame = budget.resolve(**flags)
        fuel = frame[frame["equipment_id"] == "fuel"].iloc[0]
        assert fuel["mass"] == pytest.approx(5.0)


# --- grouping ------------------------------------------------------------------


@pytest.mark.parametrize("flags", ALL_FLAGS)
def test_groupings_reconcile(budget, flags):
    """All three axes must sum to the grand total, for every flag combination."""
    expected = kg(budget.total_mass(**flags))
    for view in (
        budget.by_location(**flags),
        budget.by_responsibility(**flags),
        budget.by_subsystem(**flags),
    ):
        assert view["mass"].sum() == pytest.approx(expected)


def test_harness_takes_its_location_responsibility(budget):
    """Harness is its own subsystem, but sums under its location's responsibility."""
    assert "Harness" in budget.by_subsystem().index
    assert "Harness" not in budget.by_responsibility().index
    assert "Platform" in budget.by_responsibility().index


def test_harness_uses_cbe_and_excludes_propellant(budget):
    """
    Harness is 10% of the 10 kg Platform equipment mass, before margin.

    It would be 2.0 kg if the margined mass were used, and 1.5 kg if the 5 kg of
    propellant at the same location counted towards the base.
    """
    harness = budget.equipment.query("subsystem == 'Harness'")
    assert len(harness) == 1
    assert harness.iloc[0]["eqpt_total_mass"] == pytest.approx(1.0)


@pytest.mark.parametrize("flags", ALL_FLAGS)
def test_harness_present_in_every_case(budget, flags):
    frame = budget.resolve(**flags)
    assert (frame["subsystem"] == "Harness").sum() == 1


# --- the named queries ---------------------------------------------------------


def test_platform_and_payload_split_the_total(budget):
    """With no mixed responsibilities the two axes agree, and they partition."""
    platform = kg(budget.platform_mass())
    payload = kg(budget.payload_mass())
    assert platform == pytest.approx(30.32)  # 24 + 1.32 + 5 propellant
    assert payload == pytest.approx(30.0)
    assert platform + payload == pytest.approx(kg(budget.in_orbit_mass()))
    assert kg(budget.platform_mass(by_location=False)) == pytest.approx(platform)


def test_mixed_responsibility_splits_the_two_axes(tmp_path):
    """A box on the payload owned by the platform team lands differently per axis."""
    rows = [
        "box_b,Box B,Payload,Payload,Optics,20 kg,50,1,equipment,",
        "tracker,Star tracker,Payload,Platform,ADCS,10 kg,0,1,equipment,",
    ]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert kg(budget.payload_mass(by_location=True)) == pytest.approx(40.0)
    assert kg(budget.payload_mass(by_location=False)) == pytest.approx(30.0)
    assert kg(budget.platform_mass(by_location=False)) == pytest.approx(10.0)


def test_subsystem_mass_carries_no_system_margin(budget):
    """Platform's 20% must not reach a subsystem sum."""
    assert kg(budget.subsystem_mass("ADCS")) == pytest.approx(20.0)
    assert kg(budget.subsystem_mass("ADCS", eqpt_margin=False)) == pytest.approx(10.0)


def test_subsystem_mass_picks_up_propellant(budget):
    """Propulsion reports wet because the propellant row names it as its subsystem."""
    assert kg(budget.subsystem_mass("Propulsion")) == pytest.approx(5.0)


def test_propellant_mass(budget):
    assert kg(budget.propellant_mass()) == pytest.approx(5.0)


# --- the tabulated report ------------------------------------------------------


def row_value(report, row_type, column="total_mass_with_sys_margin"):
    return report.loc[report["row_type"] == row_type, column].iloc[0]


@pytest.mark.parametrize(
    "in_orbit, expected_total",
    [(True, 60.32), (False, 64.32)],
)
def test_tabulated_wet_total_matches_the_scalar_api(budget, in_orbit, expected_total):
    report = budget.tabulated_mass(in_orbit=in_orbit)
    assert row_value(report, "wet_total") == pytest.approx(expected_total)


def test_tabulated_propellant_row(budget):
    report = budget.tabulated_mass()
    assert row_value(report, "propellant") == pytest.approx(
        kg(budget.propellant_mass())
    )


def test_tabulated_dry_plus_propellant_is_wet(budget):
    report = budget.tabulated_mass()
    dry = row_value(report, "dry_total")
    propellant = row_value(report, "propellant")
    assert dry + propellant == pytest.approx(row_value(report, "wet_total"))


def test_tabulated_subtotals_roll_up(budget):
    """Subsystem subtotals sum to their location, and locations to the dry total."""
    report = budget.tabulated_mass()

    for location in report.loc[report["row_type"] == "location_subtotal", "location"]:
        blocks = report[
            (report["row_type"] == "subsystem_subtotal")
            & (report["location"] == location)
        ]
        subtotal = report[
            (report["row_type"] == "location_subtotal")
            & (report["location"] == location)
        ].iloc[0]
        assert blocks["eqpt_total_mass_with_margin"].sum() == pytest.approx(
            subtotal["eqpt_total_mass_with_margin"]
        )

    location_totals = report.loc[
        report["row_type"] == "location_total", "total_mass_with_sys_margin"
    ]
    assert location_totals.sum() == pytest.approx(row_value(report, "dry_total"))


def test_tabulated_excludes_propellant_from_the_blocks(budget):
    """Every subtotal above the propellant line is a dry mass."""
    report = budget.tabulated_mass()
    assert "fuel" not in set(report["label"])
    propulsion = report[
        (report["row_type"] == "subsystem_subtotal")
        & (report["subsystem"] == "Propulsion")
    ]
    assert propulsion.empty


def test_tabulated_launcher_block_appears_on_ground(budget):
    assert "Launcher" not in set(budget.tabulated_mass(in_orbit=True)["location"])
    assert "Launcher" in set(budget.tabulated_mass(in_orbit=False)["location"])


# --- validation ----------------------------------------------------------------


def test_units_are_converted(tmp_path):
    """A mass entered in grams lands in the frame as kilograms."""
    rows = ["imu,IMU,Payload,Payload,ADCS,750 g,0,2,equipment,"]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert kg(budget.total_mass()) == pytest.approx(1.5)


def test_zero_units_contributes_nothing(tmp_path):
    rows = [
        "box_b,Box B,Payload,Payload,Optics,20 kg,50,1,equipment,",
        "spare,Spare,Payload,Payload,Optics,99 kg,0,0,equipment,",
    ]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert kg(budget.total_mass()) == pytest.approx(30.0)


def test_blank_mass_class_defaults_to_equipment(tmp_path):
    rows = ["box_b,Box B,Payload,Payload,Optics,20 kg,50,1,,"]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert kg(budget.total_mass()) == pytest.approx(30.0)


@pytest.mark.parametrize(
    "row, expected",
    [
        ("star tracker,Box,Payload,Payload,ADCS,1 kg,0,1,equipment,", "equipment_id"),
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
    """Physically distinct items may share an id when they sit in different places."""
    rows = [
        "box,Box,Payload,Payload,ADCS,1 kg,0,1,equipment,",
        "box,Box,Platform,Platform,ADCS,2 kg,0,1,equipment,",
    ]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert len(budget.equipment[budget.equipment["equipment_id"] == "box"]) == 2
