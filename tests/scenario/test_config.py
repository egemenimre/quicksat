# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for reading the scenario file: the triggers, the constraints, the
activities, and the checks on the whole file.
"""

from datetime import datetime

import pytest
import yaml
from astropy.tests.helper import assert_quantity_allclose
from astropy.units import Quantity

from quicksat import Q_
from quicksat.scenario.config import (
    Activity,
    OrbitCount,
    Scenario,
    Slew,
    parse_constraint,
    parse_trigger,
)
from quicksat.utils.intervals import TimeArray

BASE = {
    "orbit": {"tle_file": "sso_510km.tle"},
    "start": "2026-10-01T00:00:00",
    "duration": "3 orbits",
    "attitudes": {
        "nadir": {"nadir_axis": "+z", "orbit_normal": "-y"},
        "sun pointing": {"sun_axis": "-z", "constrain_to_orbit_normal": "-y"},
    },
    "activities": [["eclipse entry", "sun pointing", "idle", "sunlit"]],
}
"""A valid scenario, for each test to change one part of."""


def scenario(**changes) -> Scenario:
    """The base scenario with some keys changed, read from YAML text."""
    return Scenario.from_yaml_text(yaml.safe_dump(BASE | changes))


# ---------------------------------------------------------------- Triggers


def test_a_duration_trigger():
    trigger = parse_trigger("20 min")
    assert trigger.duration == Q_(20, "min")
    assert trigger.event is None
    assert trigger.event_key is None


@pytest.mark.parametrize(
    ("text", "event", "latitude", "direction", "offset"),
    [
        ("eclipse entry", "eclipse entry", None, None, None),
        ("Eclipse  Exit", "eclipse exit", None, None, None),
        ("umbra entry", "umbra entry", None, None, None),
        ("umbra exit - 5 s", "umbra exit", None, None, "-5 s"),
        ("ascending node", "latitude crossing", 0, "ascending", None),
        ("descending node - 30 s", "latitude crossing", 0, "descending", "-30 s"),
        ("latitude 30 deg ascending", "latitude crossing", 30, "ascending", None),
        ("latitude -30 deg descending", "latitude crossing", -30, "descending", None),
        ("latitude 45 deg", "latitude crossing", 45, None, None),
        ("latitude -30deg", "latitude crossing", -30, None, None),
        ("eclipse entry + 2 min", "eclipse entry", None, None, "2 min"),
        ("eclipse entry+2min", "eclipse entry", None, None, "2 min"),
        ("latitude 45 deg -2 min", "latitude crossing", 45, None, "-2 min"),
    ],
)
def test_an_event_trigger(text, event, latitude, direction, offset):
    trigger = parse_trigger(text)
    assert trigger.duration is None
    assert trigger.event == event
    assert trigger.direction == direction
    if latitude is None:
        assert trigger.latitude is None
    else:
        assert_quantity_allclose(trigger.latitude, Q_(latitude, "deg"))
    if offset is None:
        assert trigger.offset is None
    else:
        assert_quantity_allclose(trigger.offset, Q_(offset))


def test_a_latitude_in_radians_is_kept_in_degrees():
    trigger = parse_trigger("latitude 0.5 rad descending")
    assert trigger.latitude is not None
    assert trigger.latitude.unit == Q_(1, "deg").unit
    assert_quantity_allclose(trigger.latitude, Q_(0.5, "rad"))


def test_the_event_key_names_the_event_without_the_offset():
    assert parse_trigger("eclipse entry + 2 min").event_key == ("eclipse entry",)
    assert parse_trigger("latitude 45 deg").event_key == (
        "latitude crossing",
        45.0,
        None,
    )
    assert (
        parse_trigger("ascending node").event_key
        == parse_trigger("latitude 0 deg ascending - 1 min").event_key
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("latitude 30", "Write a latitude crossing"),
        ("latitude 30 deg north", "Write a latitude crossing"),
        ("latitude 95 deg", "from -90 to 90 deg"),
        ("latitude 30 km", "angle unit"),
        ("eclipse entry + 2", "offset that is not a time"),
        ("eclipse entry + 2 m", "offset that is not a time"),
        ("eclipse entry + -2 min", "not understood"),
        ("20 min + 2 min", "not understood"),
        ("eclipse", "not understood"),
        ("5 km", "not a time"),
        ("0 s", "must be positive"),
        ("-5 min", "must be positive"),
    ],
)
def test_a_trigger_that_is_not_understood(text, message):
    with pytest.raises(ValueError, match=message):
        parse_trigger(text)


def test_a_trigger_that_is_not_text():
    with pytest.raises(ValueError, match="not text"):
        parse_trigger(20)  # pyright: ignore[reportArgumentType]


# ---------------------------------------------------------------- Constraints and activities


@pytest.mark.parametrize(
    ("text", "constraint"),
    [
        ("sunlit", "sunlit"),
        ("penumbra", "penumbra"),
        ("Umbra", "umbra"),
        (" Eclipse ", "eclipse"),
    ],
)
def test_a_constraint(text, constraint):
    assert parse_constraint(text) == constraint


@pytest.mark.parametrize(
    ("text", "message"), [("dark", "not understood"), ("lit", "'sunlit', 'penumbra'")]
)
def test_a_constraint_that_is_not_understood(text, message):
    with pytest.raises(ValueError, match=message):
        parse_constraint(text)


def test_an_activity_has_three_or_four_fields():
    three = Activity.from_fields(["10 min", "nadir", "downlink"])
    four = Activity.from_fields(["10 min", "nadir", "downlink", "sunlit"])
    assert three.constraint is None
    assert four.constraint == "sunlit"
    with pytest.raises(ValueError, match="three or four"):
        Activity.from_fields(["10 min", "nadir"])
    with pytest.raises(ValueError, match="mode must be a name"):
        Activity.from_fields(["10 min", "nadir", " "])


# ---------------------------------------------------------------- The whole file


def test_the_base_scenario_reads():
    read = scenario()
    assert read.duration == OrbitCount(3)
    assert read.step == Q_(10, "s")
    assert read.attitudes.names == ["nadir", "sun pointing"]
    assert read.source_text is not None
    assert read.source_file is None


def test_a_file_keeps_its_path_and_text(data_dir):
    path = data_dir / "scenario.yaml"
    read = Scenario.from_yaml_file(path)
    assert read.source_file == path
    assert read.source_text == path.read_text()
    # a relative TLE path is taken from the folder of the file
    assert read.orbit.tle_file == data_dir / "sso_510km.tle"


def test_the_orbit_needs_exactly_one_key():
    with pytest.raises(ValueError, match="exactly one key"):
        scenario(
            orbit={"tle_file": "a.tle", "sso": {"altitude": "510 km", "ltan": "10:30"}}
        )
    with pytest.raises(ValueError, match="exactly one key"):
        scenario(orbit={"trajectory": "a.oem"})


@pytest.mark.parametrize(
    ("ltan", "hours"), [("10:30", 10.5), ("13:30:36", 13.51), ("10.5 h", 10.5)]
)
def test_the_ltan_is_a_time_of_day(ltan, hours):
    read = scenario(orbit={"sso": {"altitude": "510 km", "ltan": ltan}})
    assert read.orbit.sso is not None
    assert_quantity_allclose(read.orbit.sso.ltan, Q_(hours, "h"))


def test_an_unquoted_ltan_is_refused_with_the_reason():
    # YAML reads an unquoted 10:30 as the base-60 number 630
    text = yaml.safe_dump(BASE).replace(
        "tle_file: sso_510km.tle", "sso: {altitude: 510 km, ltan: 10:30}"
    )
    with pytest.raises(ValueError, match="put it in quotes"):
        Scenario.from_yaml_text(text)


@pytest.mark.parametrize("ltan", ["24:00", "10:75", "25 h", "noon"])
def test_an_ltan_out_of_range_is_refused(ltan):
    with pytest.raises(ValueError, match="ltan"):
        scenario(orbit={"sso": {"altitude": "510 km", "ltan": ltan}})


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        ("5 h", Q_(5, "h")),
        ("3 orbits", OrbitCount(3)),
        ("1 orbit", OrbitCount(1)),
        ("1.5 Orbits", OrbitCount(1.5)),
    ],
)
def test_the_duration_is_a_time_or_a_number_of_orbits(duration, expected):
    read = scenario(duration=duration)
    if isinstance(expected, Quantity):
        assert_quantity_allclose(read.duration, expected)  # pyright: ignore[reportArgumentType]
    else:
        assert read.duration == expected


@pytest.mark.parametrize(
    ("duration", "message"),
    [
        (5, "a time with a unit"),
        ("5 km", "a time with a unit"),
        ("0 orbits", "positive"),
        ("-1 h", "positive"),
    ],
)
def test_a_duration_that_is_not_one_is_refused(duration, message):
    with pytest.raises(ValueError, match=message):
        scenario(duration=duration)


def test_the_step_must_be_shorter_than_a_timed_duration():
    with pytest.raises(ValueError, match="step must be shorter"):
        scenario(duration="5 min", step="10 min")


@pytest.mark.parametrize(
    "start", ["2026-10-01T00:00:00", "2026-10-01 00:00:00", datetime(2026, 10, 1)]
)
def test_the_start_is_an_iso_time_in_utc(start):
    read: TimeArray = scenario(start=start).start
    assert read.utc.isot == "2026-10-01T00:00:00.000"


def test_an_activity_must_name_a_defined_attitude():
    attitudes = {"nadir": {"nadir_axis": "+z", "orbit_normal": "-y"}}
    with pytest.raises(ValueError, match="'sun pointing' is not defined"):
        scenario(attitudes=attitudes)


@pytest.mark.parametrize(
    ("sun_pointing", "message"),
    [
        ({"sun_axis": "-z"}, "exactly one"),
        (
            {
                "sun_axis": "-z",
                "constrain_to_nadir": "+y",
                "constrain_to_orbit_normal": "-y",
            },
            "exactly one",
        ),
        ({"sun_axis": "-z", "constrain_to_nadir": "+z"}, "different body axes"),
    ],
)
def test_sun_pointing_needs_one_constraint_on_another_axis(sun_pointing, message):
    attitudes = BASE["attitudes"] | {"sun pointing": sun_pointing}
    with pytest.raises(ValueError, match=message):
        scenario(attitudes=attitudes)


def test_a_wrong_activity_is_named_by_its_number():
    activities = [["10 min", "nadir", "idle"], ["latitude 30", "nadir", "idle"]]
    with pytest.raises(ValueError, match="activity 2: trigger 'latitude 30'"):
        scenario(activities=activities)


# ---------------------------------------------------------------- Slews


def test_without_a_slew_block_attitude_changes_are_instant():
    assert scenario().slew is None


def test_a_slew_block_reads_its_limits():
    read = scenario(
        slew={"max_rate": "0.7 deg/s", "max_acceleration": "0.08 deg/s2"}
    ).slew
    assert read is not None
    assert_quantity_allclose(read.max_rate, Q_(0.7, "deg / s"))
    assert_quantity_allclose(read.max_acceleration, Q_(0.08, "deg / s2"))
    assert read.settling_time == Q_(0, "s")
    # 90 deg: 90 / 0.7 s at the peak rate, plus 0.7 / 0.08 s to speed up and slow down
    assert_quantity_allclose(
        read.turn_time(Q_(90, "deg")), Q_(137.321, "s"), atol=Q_(1, "ms")
    )


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({}, "max_rate, max_acceleration, or both"),
        ({"max_rate": "0 deg/s"}, "must be positive"),
        ({"max_rate": "1 deg"}, "angular rate"),
        ({"max_acceleration": "1 deg/s"}, "angular acceleration"),
        ({"max_rate": "1 deg/s", "settling": "10 s"}, "settling"),
    ],
)
def test_a_wrong_slew_block_is_refused(block, message):
    with pytest.raises(ValueError, match=message):
        Slew.model_validate(block)
