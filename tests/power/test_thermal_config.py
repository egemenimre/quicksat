# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the payload's thermal file: the surfaces, the heat flows and the
Earth's constants, with their defaults.
"""

import pytest
from astropy.tests.helper import assert_quantity_allclose
from pydantic import ValidationError

from quicksat import Q_, u
from quicksat.thermal.config import PayloadThermal

RADIATOR = "{normal: +x, area: 0.3 m2, absorptance: 0.20, emissivity: 0.85, temperature: 273 K}"
"""A typed-in radiator, for files that test the other keys."""

ONE_SURFACE = f"surfaces:\n  radiator: {RADIATOR}\n"
"""The surfaces of a file with the radiator only."""


def read(text: str) -> PayloadThermal:
    """The thermal file from YAML text."""
    return PayloadThermal.from_yaml_text(text)


def surface(line: str) -> PayloadThermal:
    """A file with one surface, written as the YAML mapping in `line`."""
    return read(f"surfaces:\n  only: {line}\n")


def test_a_surface_reads_with_its_defaults():
    radiator = read(ONE_SURFACE).surfaces["radiator"]
    assert radiator.normal == (1.0, 0.0, 0.0)
    assert_quantity_allclose(radiator.area, Q_(0.3, "m2"))
    assert radiator.absorptance.to_value("") == pytest.approx(0.20)
    assert radiator.emissivity.to_value("") == pytest.approx(0.85)
    assert radiator.temperature.unit == u.K
    assert radiator.temperature.value == 273
    assert not radiator.fixed_temperature
    assert not radiator.from_model


def test_a_surface_from_the_model_is_a_part():
    aperture = surface(
        "{part: Aperture, absorptance: 0.9, emissivity: 0.9, temperature: 20 °C, "
        "fixed_temperature: true}"
    ).surfaces["only"]
    assert aperture.from_model
    assert aperture.fixed_temperature
    assert_quantity_allclose(aperture.temperature, Q_(293.15, "K"))


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            "{part: Radiator, normal: +x, absorptance: 0.2, emissivity: 0.8, "
            "temperature: 273 K}",
            "a surface gives either part, or normal and area, not both",
        ),
        (
            "{absorptance: 0.2, emissivity: 0.8, temperature: 273 K}",
            "the name of its face in the 3D model",
        ),
        (
            "{normal: +x, area: 0 m2, absorptance: 0.2, emissivity: 0.8, "
            "temperature: 273 K}",
            "area must be above zero",
        ),
        (
            "{normal: +x, area: 1 m2, absorptance: 0, emissivity: 0.8, "
            "temperature: 273 K}",
            "absorptance must be above 0 and at most 1",
        ),
        (
            "{normal: +x, area: 1 m2, absorptance: 0.2, emissivity: 1.1, "
            "temperature: 273 K}",
            "emissivity must be above 0 and at most 1",
        ),
        (
            "{normal: +x, area: 1 m2, absorptance: 0.2, emissivity: 0.8, "
            "temperature: 0 K}",
            "above 0 K",
        ),
        (
            "{normal: +x, area: 1 m2, absorptance: 0.2, emissivity: 0.8, "
            "temperature: 273 W}",
            "temperature dimensions",
        ),
        ("{normal: +x, area: 1 m2, absorptance: 0.2, emissivity: 0.8}", "temperature"),
        (
            "{normal: +x, area: 1 m2, absorptance: 0.2, emissivity: 0.8, "
            "temperature: 273 K, fixed_temperature: maybe}",
            "fixed_temperature",
        ),
        (
            "{normal: +x, area: 1 m2, absorptance: 0.2, emissivity: 0.8, "
            "temperature: 273 K, fill_ratio: 1}",
            "fill_ratio",
        ),
    ],
)
def test_a_surface_that_does_not_suit_is_refused(line, message):
    with pytest.raises(ValidationError, match=message):
        surface(line)


def test_a_file_needs_a_surface():
    with pytest.raises(ValidationError, match="at least one surface"):
        read("surfaces: {}\n")
    with pytest.raises(ValidationError, match="surfaces"):
        read("earth: {albedo: 0.3}\n")


def test_the_heat_flows_and_the_earth_have_defaults():
    thermal = read(ONE_SURFACE)
    assert thermal.heat_flows == {}
    assert thermal.earth.albedo.to_value("") == pytest.approx(0.30)
    assert_quantity_allclose(thermal.earth.infrared, Q_(237, "W/m2"))


def test_a_heat_flow_is_one_power_or_one_for_each_mode():
    thermal = read(
        ONE_SURFACE + "heat_flows:\n"
        "  platform interface: -3 W\n"
        "  x-band rf: {idle: 0 W, imaging: 0 W, downlink: -5 W}\n"
    )
    assert_quantity_allclose(thermal.heat_flows["platform interface"], Q_(-3, "W"))
    assert list(thermal.flows_by_mode) == ["x-band rf"]
    assert thermal.flow_watts("downlink") == {
        "platform interface": -3.0,
        "x-band rf": -5.0,
    }
    assert thermal.flow_watts("idle")["x-band rf"] == 0.0


@pytest.mark.parametrize(
    ("flows", "message"),
    [
        ("  a: 3 kg\n", "(?s)a.power.*power dimensions"),
        ("  a: {idle: 3 kg}\n", "(?s)a.by mode.idle.*power dimensions"),
        ("  a: {}\n", "gives no mode"),
        ("  a: [1 W, 2 W]\n", "a.power"),
    ],
)
def test_a_heat_flow_that_does_not_suit_is_refused(flows, message):
    with pytest.raises(ValidationError, match=message):
        read(ONE_SURFACE + "heat_flows:\n" + flows)


@pytest.mark.parametrize(
    ("earth", "message"),
    [
        ("{albedo: 1.2}", "albedo must be from 0 to 1"),
        ("{albedo: -0.1}", "must not be negative"),
        ("{infrared: -5 W/m2}", "must not be negative"),
        ("{infrared: 237 W}", "flux dimensions"),
        ("{sun: 1361 W/m2}", "sun"),
    ],
)
def test_an_earth_that_does_not_suit_is_refused(earth, message):
    with pytest.raises(ValidationError, match=message):
        read(ONE_SURFACE + f"earth: {earth}\n")


def test_an_albedo_of_zero_is_allowed():
    assert read(ONE_SURFACE + "earth: {albedo: 0}\n").earth.albedo.value == 0


def test_every_block_and_the_file_may_hold_comments():
    thermal = read(
        "comments: The whole file.\n"
        "surfaces:\n"
        "  comments: All the surfaces.\n"
        f"  radiator: {RADIATOR[:-1]}, comments: White paint.}}\n"
        "heat_flows:\n"
        "  comments: All the flows.\n"
        "  mounts: -3 W\n"
        "earth: {comments: The defaults.}\n"
    )
    assert thermal.comments == "The whole file."
    assert list(thermal.surfaces) == ["radiator"]
    assert thermal.surfaces["radiator"].comments == "White paint."
    assert list(thermal.heat_flows) == ["mounts"]
    assert thermal.earth.comments == "The defaults."


@pytest.mark.parametrize("text", ["- a\n- b\n", "just text\n"])
def test_a_file_that_is_not_a_mapping_is_refused(text):
    with pytest.raises(ValueError, match="mapping"):
        read(text)


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        PayloadThermal.from_yaml_file(tmp_path / "payload_thermal.yaml")


def test_the_file_is_remembered(tmp_path):
    path = tmp_path / "payload_thermal.yaml"
    path.write_text(ONE_SURFACE)
    thermal = PayloadThermal.from_yaml_file(path)
    assert thermal.source_file == path
    assert thermal.source_text == ONE_SURFACE
