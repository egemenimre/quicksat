# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the power system file: the panels, the efficiencies, the switch for the
self-shadowing, the battery and the conditioning.
"""

import numpy as np
import pytest
from pydantic import ValidationError

from quicksat import u
from quicksat.power.config import DEFAULT_POINTS, PowerSystem

HEAD = "cell_efficiency: 30 %\nloss_factor: 0.80\n"
"""The two efficiencies, for files that test the panels."""


def read(text: str) -> PowerSystem:
    """The power generation from YAML text."""
    return PowerSystem.from_yaml_text(text)


def panel(line: str) -> PowerSystem:
    """A file with one panel, written as the YAML mapping in `line`."""
    return read(HEAD + f"panels:\n  only: {line}\n")


def test_the_fixture_reads(power_system):
    assert power_system.cell_efficiency.to_value("") == pytest.approx(0.30)
    assert power_system.loss_factor.to_value("") == pytest.approx(0.80)
    assert list(power_system.panels) == [
        "wing +y inner",
        "wing +y outer",
        "wing -y inner",
        "wing -y outer",
        "deck",
        "side +x",
    ]
    assert power_system.panels["deck"].from_model
    assert not power_system.panels["side +x"].from_model
    assert not power_system.shading


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
        PowerSystem.from_yaml_file(tmp_path / "power_system.yaml")


def test_the_file_is_remembered(power_system, data_dir):
    assert power_system.source_file == data_dir / "power_system.yaml"


BATTERY = "battery: {capacity: 1024 W h, capacity_factor: 0.80, max_depth_of_discharge: 30 %}\n"
CONDITIONING = (
    "conditioning: {array_regulator: 0.96, battery_charge: 0.95, "
    "battery_discharge: 0.95, distribution: 0.97}\n"
)
ONE_PANEL = "panels:\n  only: {normal: +x, area: 1 m2, fill_ratio: 1}\n"


def test_the_fixture_has_a_battery_and_conditioning(power_system):
    battery = power_system.battery
    assert battery is not None
    assert battery.usable.to_value(u.W * u.h) == pytest.approx(819.2)
    assert battery.initial_charge.to_value("") == 1
    assert battery.max_depth_of_discharge.to_value("") == pytest.approx(0.30)
    assert power_system.conditioning is not None
    assert power_system.conditioning.battery_charge.to_value("") == pytest.approx(0.95)
    assert power_system.system_margin is not None
    assert power_system.system_margin.to_value("") == pytest.approx(0.05)


def test_the_battery_and_the_conditioning_are_optional():
    plain = read(HEAD + ONE_PANEL)
    assert (plain.battery, plain.conditioning, plain.system_margin) == (
        None,
        None,
        None,
    )
    full = read(HEAD + ONE_PANEL + BATTERY + CONDITIONING + "system_margin: 5 %\n")
    assert full.source_text is not None
    assert full.source_text.endswith("system_margin: 5 %\n")


@pytest.mark.parametrize(
    ("block", "message"),
    [
        (BATTERY.replace("1024 W h", "0 W h"), "capacity must be above zero"),
        (BATTERY.replace("1024 W h", "36 A h"), "energy dimensions"),
        (BATTERY.replace("0.80", "1.2"), "capacity_factor must be above 0"),
        (BATTERY.replace("30 %", "0 %"), "max_depth_of_discharge must be above 0"),
        (
            BATTERY.replace("}", ", initial_charge: 0}"),
            "initial_charge must be above 0",
        ),
        (BATTERY.replace("}", ", spare: 1}"), "spare"),
        (CONDITIONING.replace("0.97", "1.1"), "distribution must be above 0"),
        (CONDITIONING.replace(", distribution: 0.97", ""), "distribution"),
        ("system_margin: 5 kg\n", "fraction dimensions"),
    ],
)
def test_a_battery_or_conditioning_that_does_not_suit_is_refused(block, message):
    with pytest.raises(ValidationError, match=message):
        read(HEAD + ONE_PANEL + block)


def test_every_block_and_the_file_may_hold_comments():
    system = read(
        "comments: The whole file.\n" + HEAD + "panels:\n"
        "  comments: All the panels.\n"
        "  side: {normal: +x, area: 0.2 m2, fill_ratio: 80 %, comments: A spare face.}\n"
        "self_shadowing: {enabled: false, comments: No model yet.}\n"
        "battery:\n"
        "  capacity: 1024 W h\n"
        "  capacity_factor: 0.80\n"
        "  max_depth_of_discharge: 30 %\n"
        "  comments: Saft VES16, 8s8p.\n"
        "conditioning:\n"
        "  array_regulator: 0.96\n"
        "  battery_charge: 0.95\n"
        "  battery_discharge: 0.95\n"
        "  distribution: 0.97\n"
        "  comments: From the PCDU datasheet.\n"
    )
    assert system.comments == "The whole file."
    assert list(system.panels) == ["side"]
    assert system.panels["side"].comments == "A spare face."
    assert system.self_shadowing is not None
    assert system.self_shadowing.comments == "No model yet."
    assert system.battery is not None
    assert system.battery.comments == "Saft VES16, 8s8p."
    assert system.conditioning is not None
    assert system.conditioning.comments == "From the PCDU datasheet."


def test_no_panel_may_take_the_name_of_the_comments():
    with pytest.raises(ValueError, match="no item may take that name"):
        read(
            HEAD + "panels:\n  comments: {normal: +x, area: 0.2 m2, fill_ratio: 80 %}\n"
        )
