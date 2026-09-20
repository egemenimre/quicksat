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
"""

import pytest
from pint.testing import assert_allclose

from quicksat import Q_
from quicksat.dataflow.budget import DataBudget, DataFlowModel
from quicksat.utils.orbit import Orbit

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
  orbits_without_contact: 3
"""

ORBIT = "altitude: 500 km\ninclination: 97.4 deg\n"


def build(model=MODEL, orbit=ORBIT):
    return DataBudget(DataFlowModel.from_yaml_text(model), Orbit.from_yaml_text(orbit))


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
    assert_allclose(getattr(budget, attribute), Q_(expected, unit), rtol=1e-4)


def test_margin(budget):
    assert_allclose(budget.margin, Q_(0.12, "dimensionless"), rtol=1e-4)


def test_the_two_periods_are_consistent(budget):
    """Per-day and per-orbit differ by exactly the orbit count, on both sides."""
    n = budget.orbit.orbits_per_day
    assert_allclose(budget.generated_per_orbit * n, budget.generated_per_day)
    assert_allclose(budget.downlinked_per_orbit * n, budget.downlinked_per_day)


def test_margin_is_independent_of_the_byte_convention(budget):
    """
    The margin is a ratio, so the unit cancels.

    This is what makes it the one figure that survives a decimal/binary
    disagreement between two sources.
    """
    decimal = budget.downlinked_per_day.to("GB") / budget.generated_per_day.to("GB")
    binary = budget.downlinked_per_day.to("GiB") / budget.generated_per_day.to("GiB")
    assert_allclose(decimal, binary)


def test_compression_divides_the_raw_rate(budget):
    raw = budget.model.generation.raw_datarate
    ratio = budget.model.generation.compression_ratio
    assert_allclose(budget.effective_datarate * ratio, raw)


# --- storage -----------------------------------------------------------------


def test_storage_defaults_to_the_configured_orbits(budget):
    assert_allclose(budget.storage_required(), budget.generated_per_orbit * 3)


def test_storage_scales_with_its_argument(budget):
    one = budget.storage_required(1)
    assert_allclose(budget.storage_required(6), 6 * one)
    assert_allclose(budget.storage_required(0), Q_(0.0, "GB"))


# --- the case the tool exists to catch ---------------------------------------


def test_a_negative_margin_when_generation_outruns_downlink():
    budget = build(model=MODEL.replace("duty_cycle: 5 %", "duty_cycle: 10 %"))
    assert budget.margin.magnitude < 0
    assert budget.generated_per_day > budget.downlinked_per_day


def test_margin_responds_to_each_side():
    """More contacts helps; a faster instrument hurts."""
    base = build().margin.magnitude
    more_contacts = build(
        model=MODEL.replace("contacts_per_day: 7", "contacts_per_day: 9")
    )
    faster = build(model=MODEL.replace("raw_datarate: 1000", "raw_datarate: 1200"))
    assert more_contacts.margin.magnitude > base
    assert faster.margin.magnitude < base


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ("raw_datarate: 1000 Mbit/s", "raw_datarate: 500 km", "data rate dimensions"),
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
        data_dir / "pl_dataflow_model.yaml", data_dir / "orbit.yaml"
    )
    assert_allclose(budget.margin, Q_(0.12, "dimensionless"), rtol=1e-3)


# --- the report --------------------------------------------------------------


def test_report_rows_match_the_properties(budget):
    frame = budget.tabulated_data().data
    value = lambda item: frame.loc[frame["item"] == item, "value"].iloc[0]  # noqa: E731

    assert value("Margin") == pytest.approx(budget.margin.magnitude * 100)
    assert_allclose(Q_(value("Storage required"), "GB"), budget.storage_required())
    assert_allclose(
        Q_(value("Data generation rate"), "Mbit/s"), budget.effective_datarate
    )


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
