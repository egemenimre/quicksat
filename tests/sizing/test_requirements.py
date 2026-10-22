# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the requirements file: what the mission asks of the spacecraft.
"""

import pytest
from astropy.tests.helper import assert_quantity_allclose

from quicksat import Q_
from quicksat.agility.budget import Axis
from quicksat.utils.requirements import Requirements

SAMPLE = """
agility:
  slews:
    roll_40: {axis: roll, angle: 40 deg, duration: 90 s}
    pitch_40: {axis: pitch, angle: 40 deg, duration: 1.5 min}
data:
  orbits_without_downlink: 3
"""


def test_the_sections_load():
    requirements = Requirements.from_yaml_text(SAMPLE)
    assert requirements.agility is not None and requirements.data is not None
    pitch = requirements.agility.slews["pitch_40"]
    assert pitch.axis is Axis.PITCH
    assert_quantity_allclose(pitch.duration, Q_(90, "s"))
    assert requirements.data.orbits_without_downlink == 3


@pytest.mark.parametrize("text", ["", "comments: none yet\n"])
def test_a_file_with_no_requirement_gives_none(text):
    requirements = Requirements.from_yaml_text(text)
    assert requirements.agility is None and requirements.data is None


def test_each_section_is_optional():
    requirements = Requirements.from_yaml_text("data:\n  orbits_without_downlink: 3\n")
    assert requirements.agility is None


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ("axis: roll", "axis: yaw", "roll"),
        ("angle: 40 deg, duration: 90 s", "angle: 40 s, duration: 90 s", "angle"),
        ("duration: 90 s", "duration: -90 s", "must not be negative"),
        ("orbits_without_downlink: 3", "orbits_without_downlink: -1", "greater than"),
    ],
)
def test_validation_failures(old, new, expected):
    with pytest.raises(ValueError, match=expected):
        Requirements.from_yaml_text(SAMPLE.replace(old, new))


def test_the_input_files_load(data_dir):
    requirements = Requirements.from_yaml_file(data_dir / "requirements.yaml")
    assert requirements.agility is not None
    assert list(requirements.agility.slews) == ["roll_40", "pitch_40"]


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        Requirements.from_yaml_file("no/such/requirements.yaml")
