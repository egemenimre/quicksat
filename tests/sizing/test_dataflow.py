# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the data and downlink budget.

The fixture is the sample satellite, in a 500 km orbit of 5677 s:

    generation   1000 Mbit/s raw / 2.4x compression = 416.67 Mbit/s,
                 for 5% of each orbit = 283.85 s  ->  14.78 GB/orbit
    downlink     800 Mbit/s for 7 contacts a day of 6 min = 42 min/day
                                                    ->  252.00 GB/day
    margin       252.00 / 225.00 - 1 = +12%
    storage      3 orbits without contact x 14.78 GB = 44.35 GB, in a 2 TB memory
"""

import pytest
from astropy.tests.helper import assert_quantity_allclose

from quicksat import Q_, u
from quicksat.dataflow.budget import DataBudget, DataFlowModel
from quicksat.utils.mission import Mission
from quicksat.utils.requirements import Requirements

MODEL = """
generation:
  raw_datarate: 1000 Mbit/s
  compression_ratio: 2.4
  duty_cycle: 5 %
downlink:
  rate: 800 Mbit/s
  contacts_per_day: 7
  avg_contact_duration: 6 min
storage:
  capacity: 2 TB
"""

MISSION = "altitude: 500 km\ninclination: 97.4 deg\nduration: 7 yr\n"

REQUIREMENTS = "data:\n  orbits_without_contact: 3\n"


def build(model=MODEL, mission=MISSION, requirements: str | None = REQUIREMENTS):
    return DataBudget(
        DataFlowModel.from_yaml_text(model),
        Mission.from_yaml_text(mission),
        Requirements.from_yaml_text(requirements) if requirements else None,
    )


@pytest.fixture
def budget():
    return build()


# --- the chain ---------------------------------------------------------------


@pytest.mark.parametrize(
    "attribute, unit, expected",
    [
        ("effective_datarate", "Mbit/s", 416.667),
        ("generation_duration", "s", 283.849),
        ("generated_per_orbit", "GB", 14.784),
        ("generated_per_day", "GB", 225.000),
        ("contact_per_day", "min", 42.0),
        ("downlinked_per_day", "GB", 252.000),
        ("downlinked_per_orbit", "GB", 16.558),
    ],
)
def test_chain(budget, attribute, unit, expected):
    assert_quantity_allclose(getattr(budget, attribute), Q_(expected, unit), rtol=1e-4)


def test_margin(budget):
    assert_quantity_allclose(
        budget.margin, Q_(0.12, u.dimensionless_unscaled), rtol=1e-4
    )


# --- storage -----------------------------------------------------------------


def test_storage_defaults_to_the_required_orbits(budget):
    assert budget.required_orbits == 3
    assert_quantity_allclose(budget.storage_required(), budget.generated_per_orbit * 3)
    assert_quantity_allclose(budget.storage_required(), Q_(44.351, "GB"), rtol=1e-4)


def test_storage_with_no_requirement_needs_its_orbits():
    budget = build(requirements=None)
    assert budget.required_orbits is None
    with pytest.raises(ValueError, match="no data requirement"):
        budget.storage_required()
    assert_quantity_allclose(budget.storage_required(3), Q_(44.351, "GB"), rtol=1e-4)


def test_storage_scales_with_its_argument(budget):
    one = budget.storage_required(1)
    assert_quantity_allclose(budget.storage_required(6), 6 * one)
    assert_quantity_allclose(budget.storage_required(0), Q_(0.0, "GB"))


# --- the checks --------------------------------------------------------------


def test_the_downlink_and_the_memory_are_checked(budget):
    downlink, storage = budget.checks()
    assert downlink.name == "downlink"
    assert_quantity_allclose(downlink.margin, budget.margin)
    assert downlink.passes
    assert storage.name == "storage"
    assert_quantity_allclose(storage.design, Q_(2000, "GB"))
    assert_quantity_allclose(storage.limit, budget.storage_required())
    assert storage.passes


def test_a_memory_too_small_fails_its_check():
    budget = build(model=MODEL.replace("capacity: 2 TB", "capacity: 40 GB"))
    storage = budget.checks()[1]
    assert not storage.passes
    assert_quantity_allclose(storage.spare, Q_(-4.351, "GB"), rtol=1e-3)


def test_with_no_requirement_only_the_downlink_is_checked():
    assert [check.name for check in build(requirements=None).checks()] == ["downlink"]


# --- the case the tool exists to catch ---------------------------------------


def test_a_negative_margin_when_generation_outruns_downlink():
    """Twice the duty cycle generates 450 GB a day: 252 / 450 - 1 = -44%."""
    budget = build(model=MODEL.replace("duty_cycle: 5 %", "duty_cycle: 10 %"))
    assert_quantity_allclose(
        budget.margin, Q_(-0.44, u.dimensionless_unscaled), rtol=1e-4
    )


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ("raw_datarate: 1000 Mbit/s", "raw_datarate: 500 km", "data rate dimensions"),
        # the bit is a unit, so a frequency is not a data rate
        ("raw_datarate: 1000 Mbit/s", "raw_datarate: 800 MHz", "data rate dimensions"),
        # and bps is not a unit at all, rather than being read as baud
        ("raw_datarate: 1000 Mbit/s", "raw_datarate: 800 Mbps", "Mbps"),
        (
            "raw_datarate: 1000 Mbit/s",
            "raw_datarate: -10 Mbit/s",
            "must not be negative",
        ),
        (
            "compression_ratio: 2.4",
            "compression_ratio: 0.5",
            "greater than or equal to 1",
        ),
        ("duty_cycle: 5 %", "duty_cycle: 120 %", "must not exceed 100%"),
        ("contacts_per_day: 7", "contacts_per_day: -1", "greater than or equal to 0"),
        (
            "avg_contact_duration: 6 min",
            "avg_contact_duration: 6 kg",
            "time dimensions",
        ),
        ("capacity: 2 TB", "capacity: 2 km", "data volume dimensions"),
        ("capacity: 2 TB", "capacity: -2 TB", "must not be negative"),
    ],
)
def test_validation_failures(old, new, expected):
    with pytest.raises(ValueError, match=expected):
        DataFlowModel.from_yaml_text(MODEL.replace(old, new))


def test_a_missing_section_is_rejected():
    without_storage = MODEL.split("storage:")[0]
    with pytest.raises(ValueError, match="storage"):
        DataFlowModel.from_yaml_text(without_storage)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        DataFlowModel.from_yaml_file("no/such/model.yaml")


def test_input_files_load(data_dir):
    budget = DataBudget.from_yaml_file(
        data_dir / "pl_dataflow_model.yaml",
        data_dir / "mission.yaml",
        data_dir / "requirements.yaml",
    )
    assert_quantity_allclose(
        budget.margin, Q_(0.12, u.dimensionless_unscaled), rtol=1e-3
    )
    assert all(check.passes for check in budget.checks())


# --- the report --------------------------------------------------------------


def test_report_rows_match_the_properties(budget):
    frame = budget.tabulated_data().data
    value = lambda item: frame.loc[frame["item"] == item, "value"].iloc[0]  # noqa: E731

    assert value("Margin") == pytest.approx(budget.margin.value * 100)
    assert_quantity_allclose(
        Q_(value("Storage required"), "GB"), budget.storage_required()
    )
    assert_quantity_allclose(
        Q_(value("Data generation rate"), "Mbit/s"), budget.effective_datarate
    )
    assert value("Mass memory") == pytest.approx(2000)


def test_with_no_requirement_the_report_has_no_storage_required():
    items = list(build(requirements=None).tabulated_data().data["item"])
    assert "Mass memory" in items
    assert "Storage required" not in items


def test_report_hides_row_type_but_keeps_it(budget):
    report = budget.tabulated_data()
    assert "row_type" in report.data.columns
    assert "row_type" not in report.to_html()
    assert set(report.data["row_type"]) == {"input", "derived", "margin", "storage"}


def test_report_says_whether_the_budget_closes():
    closing = build().tabulated_data().data
    failing = build(model=MODEL.replace("duty_cycle: 5 %", "duty_cycle: 10 %"))
    failing = failing.tabulated_data().data

    assert "closes" == closing.loc[closing["item"] == "Margin", "comment"].iloc[0]
    assert (
        "does not close" == failing.loc[failing["item"] == "Margin", "comment"].iloc[0]
    )
