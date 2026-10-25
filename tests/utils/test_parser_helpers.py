# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the quantity types: temperatures in kelvin or Celsius, and numbers
written with underscores.
"""

import pytest
from astropy.tests.helper import assert_quantity_allclose
from pydantic import BaseModel, ConfigDict, ValidationError

from quicksat import Q_, u
from quicksat.utils.parser_helpers import MassQty, TemperatureQty


class _Reading(BaseModel):
    """One temperature and one mass, read as a file's fields are."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    temperature: TemperatureQty = Q_(293, "K")
    mass: MassQty = Q_(1, "kg")


@pytest.mark.parametrize("text", ["20 °C", "20 Celsius", "20 deg_C"])
def test_celsius_reads_as_kelvin(text):
    temperature = _Reading.model_validate({"temperature": text}).temperature
    assert temperature.unit == u.K
    assert_quantity_allclose(temperature, Q_(293.15, "K"))


def test_kelvin_is_kept():
    temperature = _Reading.model_validate({"temperature": "293 K"}).temperature
    assert temperature.unit == u.K
    assert temperature.value == 293


def test_a_difference_of_celsius_readings_has_no_offset():
    warm = _Reading.model_validate({"temperature": "30 °C"}).temperature
    cold = _Reading.model_validate({"temperature": "20 °C"}).temperature
    assert_quantity_allclose(warm - cold, Q_(10, "K"))


@pytest.mark.parametrize("text", ["0 K", "-5 K", "-300 °C"])
def test_absolute_zero_and_below_are_refused(text):
    with pytest.raises(ValidationError, match="above 0 K"):
        _Reading.model_validate({"temperature": text})


def test_a_temperature_of_another_dimension_is_refused():
    with pytest.raises(ValidationError, match="temperature dimensions"):
        _Reading.model_validate({"temperature": "5 W"})


@pytest.mark.parametrize(
    ("text", "kilograms"), [("1_000.5 kg", 1000.5), ("1.5e1_0 kg", 1.5e10)]
)
def test_underscores_in_the_number_are_taken_out(text, kilograms):
    assert_quantity_allclose(
        _Reading.model_validate({"mass": text}).mass, Q_(kilograms, "kg")
    )
