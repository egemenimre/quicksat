# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the power generation file: the panels, the efficiencies and the switch
for the self-shadowing.
"""

import numpy as np
import pytest
from pydantic import ValidationError

from quicksat.power.config import DEFAULT_POINTS, PowerGeneration

HEAD = "cell_efficiency: 30 %\nloss_factor: 0.80\n"
"""The two efficiencies, for files that test the panels."""


def read(text: str) -> PowerGeneration:
    """The power generation from YAML text."""
    return PowerGeneration.from_yaml_text(text)


def panel(line: str) -> PowerGeneration:
    """A file with one panel, written as the YAML mapping in `line`."""
    return read(HEAD + f"panels:\n  only: {line}\n")


def test_the_fixture_reads(generation):
    assert generation.cell_efficiency.to_value("") == pytest.approx(0.30)
    assert generation.loss_factor.to_value("") == pytest.approx(0.80)
    assert list(generation.panels) == [
        "wing +y inner",
        "wing +y outer",
        "wing -y inner",
        "wing -y outer",
        "deck",
        "side +x",
    ]
    assert generation.panels["deck"].from_model
    assert not generation.panels["side +x"].from_model
    assert not generation.shading


def test_a_typed_in_normal_is_an_axis_or_three_numbers():
    axis = panel("{normal: -y, area: 1 m2, fill_ratio: 1}").panels["only"]
    assert axis.normal == (0.0, -1.0, 0.0)
    numbers = panel("{normal: [0, 1, -1], area: 1 m2, fill_ratio: 1}").panels["only"]
    assert numbers.normal is not None
    np.testing.assert_allclose(numbers.normal, [0, 2**-0.5, -(2**-0.5)])


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("{part: Deck cells, normal: +x, fill_ratio: 1}", "not both"),
        ("{normal: +x, fill_ratio: 1}", "or both normal and area"),
        ("{area: 1 m2, fill_ratio: 1}", "or both normal and area"),
        ("{fill_ratio: 1}", "either part"),
        ("{part: ' ', fill_ratio: 1}", "part must not be empty"),
        ("{normal: +x, area: 0 m2, fill_ratio: 1}", "area must be above zero"),
        ("{normal: +x, area: 1 kg, fill_ratio: 1}", "area dimensions"),
        ("{normal: x, area: 1 m2, fill_ratio: 1}", "signed body axis"),
        ("{normal: [1, 0], area: 1 m2, fill_ratio: 1}", "three numbers"),
        ("{normal: [0, 0, 0], area: 1 m2, fill_ratio: 1}", "three zeros"),
        ("{normal: +x, area: 1 m2, fill_ratio: 0}", "above 0 and at most 1"),
        ("{normal: +x, area: 1 m2, fill_ratio: 101 %}", "above 0 and at most 1"),
        ("{normal: +x, area: 1 m2}", "fill_ratio"),
        ("{normal: +x, area: 1 m2, fill_ratio: 1, tilt: 3 deg}", "tilt"),
    ],
)
def test_a_panel_that_does_not_suit_is_refused(line, message):
    with pytest.raises(ValidationError, match=message):
        panel(line)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("cell_efficiency: 0\nloss_factor: 1\n", "cell_efficiency must be above 0"),
        ("cell_efficiency: 1\nloss_factor: 1.2\n", "loss_factor must be above 0"),
        ("cell_efficiency: 30 W\nloss_factor: 1\n", "fraction dimensions"),
    ],
)
def test_an_efficiency_outside_0_to_1_is_refused(text, message):
    with pytest.raises(ValidationError, match=message):
        read(text + "panels:\n  only: {normal: +x, area: 1 m2, fill_ratio: 1}\n")


def test_a_file_needs_a_panel():
    with pytest.raises(ValidationError, match="at least one panel"):
        read(HEAD + "panels: {}\n")


def test_the_self_shadowing_has_a_switch():
    panels = "panels:\n  only: {normal: +x, area: 1 m2, fill_ratio: 1}\n"
    on = read(HEAD + panels + "self_shadowing: {enabled: true}\n")
    assert on.shading
    assert on.self_shadowing is not None
    assert on.self_shadowing.points == DEFAULT_POINTS
    off = read(HEAD + panels + "self_shadowing: {enabled: false, points: 128}\n")
    assert not off.shading
    with pytest.raises(ValidationError, match="enabled"):
        read(HEAD + panels + "self_shadowing: {points: 128}\n")
    with pytest.raises(ValidationError, match="greater than 0"):
        read(HEAD + panels + "self_shadowing: {enabled: true, points: 0}\n")


@pytest.mark.parametrize("text", ["", "- a list\n"])
def test_a_file_that_is_not_a_mapping_is_refused(text):
    with pytest.raises(ValueError):
        read(text)


def test_a_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        PowerGeneration.from_yaml_file(tmp_path / "power_generation.yaml")


def test_the_file_is_remembered(generation, data_dir):
    assert generation.source_file == data_dir / "power_generation.yaml"
