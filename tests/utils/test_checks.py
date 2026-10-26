# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for a budget's checks: the spare, the margin and the verdict, for each kind of
limit.
"""

import math

from astropy.tests.helper import assert_quantity_allclose

from quicksat import Q_
from quicksat.utils.checks import Check, tabulate

PROPELLANT = Check("propellant", "loaded covers required", Q_(22, "kg"), Q_(25, "kg"))
"""A limit to reach, missed: 3 kg short, -12% of the 25 kg needed."""

SLEW = Check("roll_40", "40 deg in 90 s", Q_(80, "s"), Q_(90, "s"), at_most=True)
"""A limit not to pass, met: 10 s to spare, +12.5% of the 80 s used."""


def test_a_limit_to_reach():
    assert_quantity_allclose(PROPELLANT.spare, Q_(-3, "kg"))
    assert PROPELLANT.margin.value == -0.12
    assert not PROPELLANT.passes


def test_a_limit_not_to_pass():
    assert_quantity_allclose(SLEW.spare, Q_(10, "s"))
    assert SLEW.margin.value == 0.125
    assert SLEW.passes


def test_the_spare_is_in_the_design_unit():
    check = Check("storage", "", Q_(2, "TB"), Q_(44, "GB"))
    assert check.spare.unit == check.design.unit
    assert_quantity_allclose(check.spare, Q_(1956, "GB"))


def test_meeting_the_limit_exactly_passes():
    assert Check("x", "", Q_(90, "s"), Q_(90, "s"), at_most=True).passes


def test_a_need_of_zero_gives_an_infinite_margin():
    check = Check("storage", "no gap between contacts", Q_(2, "TB"), Q_(0, "GB"))
    assert math.isinf(check.margin.value)
    assert check.passes


def test_the_table_writes_data_volumes_in_gb():
    check = Check("storage", "", Q_(2, "TB"), Q_(44.35, "GB"))
    row = tabulate([check]).data.iloc[0]
    assert (row["design"], row["limit"], row["spare"]) == (
        "2.00 TB",
        "≥ 44.35 GB",
        "+1.96 TB",
    )


def test_the_table_has_one_row_per_check():
    table = tabulate([PROPELLANT, SLEW]).data
    assert list(table["check"]) == ["propellant", "roll_40"]
    assert list(table["verdict"]) == ["FAILS", "PASS"]
    assert list(table["margin"]) == ["-12.0 %", "+12.5 %"]
    assert table["limit"].iloc[1].startswith("≤")
