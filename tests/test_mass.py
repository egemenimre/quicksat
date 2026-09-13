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

    in orbit,  full propellant = 24 + 1.32 + 30 + 5  = 60.32 kg
    in orbit,  no propellant   =                       55.32 kg
    on ground, full propellant =              + 4    = 64.32 kg
    on ground, no propellant   =                       59.32 kg
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
    "unit_mass,eqpt_margin,number_of_units,mass_class,comments"
)

ROWS = [
    "box_a,Box A,Platform,Platform,ADCS,10 kg,100,1,equipment,",
    "box_b,Box B,Payload,Payload,Optics,20 kg,50,1,equipment,",
    "fuel,Hydrazine,Platform,Platform,Propulsion,5 kg,0,1,propellant,",
    "lv_ring,Adapter ring,Launcher,Launcher,Structure,4 kg,0,1,equipment,",
]

ALL_FLAGS = [
    {
        "propellant": propellant,
        **dict(zip(("sys_margin", "eqpt_margin", "in_orbit"), switches, strict=True)),
    }
    for propellant in (100, 50, 0)
    for switches in itertools.product([True, False], repeat=3)
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
    "in_orbit, propellant, expected",
    [
        (False, 100, 64.32),
        (False, 0, 59.32),
        (True, 100, 60.32),
        (True, 0, 55.32),
    ],
)
def test_four_mass_cases(budget, in_orbit, propellant, expected):
    total = budget.total_mass(in_orbit=in_orbit, propellant=propellant)
    assert kg(total) == pytest.approx(expected)


@pytest.mark.parametrize(
    "propellant, expected",
    [(100, 60.32), (75, 59.07), (50, 57.82), (25, 56.57), (0, 55.32)],
)
def test_propellant_depletes_linearly(budget, propellant, expected):
    """The 5 kg load burns off in proportion; the endpoints are wet and dry mass."""
    assert kg(budget.in_orbit_mass(propellant=propellant)) == pytest.approx(expected)


def test_propellant_percentage_is_range_checked(budget):
    for bad in (-1, 101):
        with pytest.raises(ValueError, match="between 0 and 100"):
            budget.in_orbit_mass(propellant=bad)


def test_case_presets_match_the_generic_method(budget):
    assert budget.in_orbit_mass() == budget.total_mass(in_orbit=True)
    assert budget.on_ground_mass() == budget.total_mass(in_orbit=False)
    assert budget.in_orbit_mass(propellant=0) == budget.total_mass(
        in_orbit=True, propellant=0
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
        if not flags["propellant"]:
            continue
        frame = budget.resolve(**flags)
        fuel = frame[frame["equipment_id"] == "fuel"].iloc[0]
        assert fuel["mass"] == pytest.approx(5.0 * flags["propellant"] / 100)


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
    harness = budget.eqpt_table.query("subsystem == 'Harness'")
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
    assert kg(budget.platform_mass(by_responsibility=True)) == pytest.approx(platform)


def test_mixed_responsibility_splits_the_two_axes(tmp_path):
    """A box on the payload owned by the platform team lands differently per axis."""
    rows = [
        "box_b,Box B,Payload,Payload,Optics,20 kg,50,1,equipment,",
        "tracker,Star tracker,Payload,Platform,ADCS,10 kg,0,1,equipment,",
    ]
    budget = MassBudget.from_csv(*write_budget(tmp_path, rows))
    assert kg(budget.payload_mass()) == pytest.approx(40.0)
    assert kg(budget.payload_mass(by_responsibility=True)) == pytest.approx(30.0)
    assert kg(budget.platform_mass(by_responsibility=True)) == pytest.approx(10.0)


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


def row_value(report, row_type, column="total_mass_with_margin"):
    return report.loc[report["row_type"] == row_type, column].iloc[0]


@pytest.mark.parametrize(
    "in_orbit, expected_total",
    [(True, 60.32), (False, 64.32)],
)
def test_tabulated_wet_total_matches_the_scalar_api(budget, in_orbit, expected_total):
    report = budget.tabulated_mass(in_orbit=in_orbit).data
    assert row_value(report, "wet_total") == pytest.approx(expected_total)


def test_tabulated_propellant_row(budget):
    report = budget.tabulated_mass().data
    assert row_value(report, "propellant") == pytest.approx(
        kg(budget.propellant_mass())
    )


def test_tabulated_dry_plus_propellant_is_wet(budget):
    report = budget.tabulated_mass().data
    dry = row_value(report, "dry_total")
    propellant = row_value(report, "propellant")
    assert dry + propellant == pytest.approx(row_value(report, "wet_total"))


def test_tabulated_subtotals_roll_up(budget):
    """Subsystem subtotals sum to their location, and locations to the dry total."""
    report = budget.tabulated_mass(subsystem_subtotals=True).data

    for location in report.loc[report["row_type"] == "location_subtotal", "location"]:
        blocks = report[
            (report["row_type"] == "subsystem_subtotal")
            & (report["location"] == location)
        ]
        subtotal = report[
            (report["row_type"] == "location_subtotal")
            & (report["location"] == location)
        ].iloc[0]
        assert blocks["total_mass_with_margin"].sum() == pytest.approx(
            subtotal["total_mass_with_margin"]
        )

    location_totals = report.loc[
        report["row_type"] == "location_total", "total_mass_with_margin"
    ]
    assert location_totals.sum() == pytest.approx(row_value(report, "dry_total"))


def test_tabulated_excludes_propellant_from_the_blocks(budget):
    """Every subtotal above the propellant line is a dry mass."""
    report = budget.tabulated_mass().data
    assert "fuel" not in set(report["equipment_id"])
    propulsion = report[
        (report["row_type"] == "subsystem_subtotal")
        & (report["subsystem"] == "Propulsion")
    ]
    assert propulsion.empty


def test_subsystem_subtotals_are_off_by_default(budget):
    """The blocks stay grouped by subsystem either way; only the lines come and go."""
    default = budget.tabulated_mass().data
    detailed = budget.tabulated_mass(subsystem_subtotals=True).data

    assert "subsystem_subtotal" not in set(default["row_type"])
    assert "subsystem_subtotal" in set(detailed["row_type"])

    def item_labels(frame):
        return list(frame.loc[frame["row_type"] == "equipment", "equipment_id"])

    assert item_labels(default) == item_labels(detailed)
    assert row_value(default, "wet_total") == pytest.approx(
        row_value(detailed, "wet_total")
    )


def test_hidden_columns_stay_in_the_frame(budget):
    """Hidden columns are only hidden: `.data` is complete whatever the flags."""
    report = budget.tabulated_mass().data
    for column in ("location", "comments", "row_type"):
        assert column in report.columns

    plain = budget.tabulated_mass().to_html()
    annotated = budget.tabulated_mass(comments=True).to_html()

    # location is always hidden -- the subtotal rows already name it
    assert "Location" not in plain
    assert "Location" not in annotated

    assert "Comments" not in plain
    assert "Comments" in annotated


def test_harness_row_explains_itself_in_the_comments(budget):
    """The derived rows carry their own derivation, which is why the flag exists."""
    report = budget.tabulated_mass().data
    harness = report.loc[report["subsystem"] == "Harness"].iloc[0]
    assert "10.0% of 10.000 kg" in harness["comments"]


def test_tabulated_launcher_block_appears_on_ground(budget):
    assert "Launcher" not in set(budget.tabulated_mass(in_orbit=True).data["location"])
    assert "Launcher" in set(budget.tabulated_mass(in_orbit=False).data["location"])


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
        ("box,Box,Payload,Payload,ADCS,1 kg,-5,1,equipment,", "eqpt_margin"),
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
    assert len(budget.eqpt_table[budget.eqpt_table["equipment_id"] == "box"]) == 2
