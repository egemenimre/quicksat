# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the user's notes in the sizing files, and for the keys they refuse.

Every block of a sizing YAML file may hold a `comments` field, as in the
scenario and power files. A key that the file does not know is refused, so that
a typo in an optional key cannot leave its default in place without a word.
"""

import pytest
from pydantic import ValidationError

from quicksat.agility.budget import AgilityConfig
from quicksat.dataflow.budget import DataFlowModel
from quicksat.delta_v.budget import DeltaVConfig
from quicksat.mass.budget import MassBudgetConfig
from quicksat.utils.mission import Mission
from quicksat.utils.requirements import Requirements

MISSION = """
comments: the reference orbit
altitude: 500 km
inclination: 97.4 deg
duration: 7 yr
"""

MASS = """
comments: the margins follow the agency's rules
locations:
  comments: one entry for each location the equipment names
  Platform:
    system_margin: 20
    harness_fraction: 4
    harness_margin: 25
    comments: the bus
"""

DATA = """
comments: daytime imaging only
generation: {raw_datarate: 1000 Mbit/s, compression_ratio: 2.4, duty_cycle: 5 %, comments: VNIR}
downlink: {rate: 800 Mbit/s, contacts_per_day: 7, avg_contact_duration: 6 min, comments: X-band}
storage: {capacity: 2 TB, comments: the SSDR}
"""

DELTA_V = """
comments: hydrazine
propulsion: {isp: 220 s, comments: monopropellant}
margin: 5
collision_avoidance: {return_burn: false, comments: the drag make-up absorbs it}
"""

AGILITY = """
comments: two axes
selected_case: first_guess
inertia_cases:
  comments: the names are the notebook's
  first_guess:
    body: {x: 1.5 m, y: 1.5 m, z: 2.0 m, comments: the bus alone}
    appendage_factor: {roll: 1.07, pitch: 1.02, comments: the arrays}
    comments: from a box
  measured:
    inertia: {roll: 264.7 kg*m**2, pitch: 280.0 kg*m**2}
wheels:
  count: 4
  elevation: 26.5 deg
  momentum: 4.0 N*m*s
  torque: 0.2 N*m
  momentum_use_factor: 33.3 %
  torque_derating: 75 %
  comments: a pyramid
settling_time: 20 s
"""

REQUIREMENTS = """
comments: from the mission requirements document
agility:
  comments: the imaging slews
  slews:
    comments: one per axis
    roll_40: {axis: roll, angle: 40 deg, duration: 90 s, comments: across track}
    pitch_40: {axis: pitch, angle: 40 deg, duration: 90 s}
data: {orbits_without_contact: 3, comments: the longest gap}
"""

FILES = [
    (Mission, MISSION),
    (MassBudgetConfig, MASS),
    (DataFlowModel, DATA),
    (DeltaVConfig, DELTA_V),
    (AgilityConfig, AGILITY),
    (Requirements, REQUIREMENTS),
]


@pytest.mark.parametrize("model, text", FILES)
def test_every_block_may_hold_comments(model, text):
    loaded = model.from_yaml_text(text)
    assert loaded.comments


def test_the_notes_on_a_section_are_not_an_item():
    mass = MassBudgetConfig.from_yaml_text(MASS)
    assert list(mass.locations) == ["Platform"]
    assert mass.locations["Platform"].comments == "the bus"
    agility = AgilityConfig.from_yaml_text(AGILITY)
    assert list(agility.inertia_cases) == ["first_guess", "measured"]
    assert agility.for_case("first_guess").comments == "from a box"
    requirements = Requirements.from_yaml_text(REQUIREMENTS)
    assert requirements.agility is not None
    assert list(requirements.agility.slews) == ["roll_40", "pitch_40"]


@pytest.mark.parametrize(
    "model, text, typo",
    [
        (Mission, MISSION, ("duration:", "durration:")),
        (MassBudgetConfig, MASS, ("harness_margin", "harness_margn")),
        (DataFlowModel, DATA, ("duty_cycle", "duty_cyle")),
        (DeltaVConfig, DELTA_V, ("return_burn", "return_brn")),
        (AgilityConfig, AGILITY, ("torque_derating", "torque_derate")),
        (Requirements, REQUIREMENTS, ("orbits_without_contact", "orbits_without")),
    ],
)
def test_an_unknown_key_is_refused(model, text, typo):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.from_yaml_text(text.replace(*typo))


def test_no_location_or_case_may_be_called_comments():
    with pytest.raises(ValidationError, match="no item may take that name"):
        MassBudgetConfig.from_yaml_text("locations:\n  comments: {system_margin: 20}\n")
    cases = "  comments:\n    inertia: {roll: 1 kg*m**2, pitch: 1 kg*m**2}\n"
    text = AGILITY.replace("  comments: the names are the notebook's\n", cases)
    with pytest.raises(ValidationError, match="no item may take that name"):
        AgilityConfig.from_yaml_text(text)
