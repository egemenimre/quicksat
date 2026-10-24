# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the articulations: the parts of the 3D model that turn to point an
axis toward a direction, such as the sun.

`articulated_run`, from the conftest, is `scenario.yaml` with slews, and with
the model and two articulations. One wing tracks the sun and parks in
`downlink`. The other turns about `-y` within a range, so the sign and the
clamp are both tested.
"""

import dataclasses

import numpy as np
import pytest
from astropy.coordinates import CartesianRepresentation

from quicksat import u
from quicksat.orbit.attitude import axis_vector
from quicksat.scenario.articulation import (
    clamp_to_range,
    hold_last,
    tracking_angles,
)
from quicksat.scenario.attitude import body_rotations
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import ScenarioRun, run_scenario
from quicksat.scenario.spacecraft import node_index, read_glb_json
from quicksat.scenario.viewer import scenario_data
from quicksat.utils.intervals import labels_at

from .conftest import ARTICULATED_MODEL, SLEW


@pytest.fixture(scope="module")
def text(data_dir) -> str:
    """The fixture scenario file, which names no model."""
    return (data_dir / "scenario.yaml").read_text()


def sun_in_body(run: ScenarioRun) -> np.ndarray:
    """Unit vectors to the sun in body axes, one for each time of the grid."""
    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    sun = run.sun.xyz.to_value(u.km).T - cartesian.xyz.to_value(u.km).T
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    return np.einsum("nji,nj->ni", body_rotations(run), sun)


def turned(axis: np.ndarray, vector: np.ndarray, angles: np.ndarray) -> np.ndarray:
    """A vector turned right-handed about an axis, by each angle in radians."""
    across = np.cross(axis, vector)
    return (
        np.outer(np.cos(angles), vector)
        + np.outer(np.sin(angles), across)
        + np.outer(1 - np.cos(angles), axis * (axis @ vector))
    )


def modes_of(run: ScenarioRun) -> np.ndarray:
    """The platform's mode at each time of the grid, the last one included."""
    modes = labels_at(run.mode["platform"], run.times)
    modes[-1] = run.occurrences[-1].activity.mode.platform
    return modes


# ---------------------------------------------------------------- The angle rules


def test_the_tracking_angle_is_zero_toward_the_sun_and_turns_right_handed():
    y, minus_z = axis_vector("+y"), axis_vector("-z")
    suns = np.array([[0, 0, -1], [-1, 0, 0], [1, 0, 0], [0, 0, 1.0]])
    angles = np.degrees(tracking_angles(y, minus_z, suns))
    # -z turned 90 degrees right-handed about +y points along -x
    assert angles[:3] == pytest.approx([0, 90, -90])
    assert abs(angles[3]) == pytest.approx(180)


def test_the_sun_off_the_plane_gives_the_angle_of_its_part_across_the_axis():
    y, minus_z = axis_vector("+y"), axis_vector("-z")
    sun = np.array([[-np.cos(0.3) * 0.6, 0.8, -np.sin(0.3) * 0.6]])
    angle = tracking_angles(y, minus_z, sun)
    # the turned sun axis meets the sun at the length of its part across the axis
    face = turned(y, minus_z, angle)
    assert face @ sun[0] == pytest.approx([0.6])


def test_the_sun_along_the_axis_leaves_the_angle_undefined():
    y, minus_z = axis_vector("+y"), axis_vector("-z")
    suns = np.array([[0, 1.0, 0], [0, -1.0, 0], [1e-7, 1.0, 0]])
    assert np.isnan(tracking_angles(y, minus_z, suns)).all()


@pytest.mark.parametrize(
    ("angles", "held"),
    [
        ([0.1, np.nan, np.nan, 0.4, np.nan], [0.1, 0.1, 0.1, 0.4, 0.4]),
        ([np.nan, np.nan, 0.3, np.nan], [0.3, 0.3, 0.3, 0.3]),
        ([np.nan, np.nan], [0.0, 0.0]),
    ],
)
def test_an_undefined_angle_keeps_the_last_one(angles, held):
    assert hold_last(np.array(angles)) == pytest.approx(held)


def test_an_angle_outside_the_range_stops_at_the_nearer_end():
    angles = np.array([0, 59, 70, 150, 170, -170, -40, 180])
    clamped = clamp_to_range(angles, -30, 60)
    # 150 is 90 from 60 and 180 from -30, going round through 180; 170 is 110
    # from 60 and 160 from -30; -170 is 140 from -30 and 130 from 60
    assert clamped == pytest.approx([0, 59, 60, 60, 60, 60, -30, 60])


# ---------------------------------------------------------------- The scenario file


def test_the_model_and_its_articulations_read(articulated_run, data_dir):
    model = articulated_run.scenario.spacecraft_model
    assert model is not None
    assert model.file == data_dir / "spacecraft.glb"
    wing = model.articulations["wing +y"]
    assert (wing.part, wing.axis, wing.point) == ("Wing +y", "+y", ("-z", "sun"))
    assert [end.to_value(u.deg) for end in wing.range] == [-180, 180]
    assert wing.park["downlink"].to_value(u.deg) == 45
    limited = model.articulations["wing -y"]
    assert [end.to_value(u.deg) for end in limited.range] == [-30, 60]


def test_the_model_and_its_articulations_may_hold_comments(text, data_dir):
    model = (
        "3d_model:\n  file: spacecraft.glb\n  comments: The sample model.\n"
        "  articulations:\n    comments: Both wings.\n"
        "    wing: {part: Wing +y, axis: +y, point: [-z, sun], comments: The +y wing.}\n"
    )
    read = Scenario.from_yaml_text(model + text, data_dir).spacecraft_model
    assert read is not None
    assert read.comments == "The sample model."
    assert list(read.articulations) == ["wing"]
    assert read.articulations["wing"].comments == "The +y wing."


def wing(fields: str) -> str:
    """A model block with one articulation, given its fields."""
    return (
        f"3d_model:\n  file: spacecraft.glb\n  articulations:\n    wing: {{{fields}}}\n"
    )


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ("part: Wing +y, axis: +y, point: [-y, sun]", "must use different body axes"),
        ("part: Wing +y, axis: +y, point: [-z, sun], range: [60 deg, -30 deg]", "rise"),
        ("part: Wing +y, axis: +y, point: [-z, sun], range: [0 deg, 270 deg]", "rise"),
        ("part: Wing +y, axis: +y, point: [-z, sun], range: [0 deg, 9 m]", "angle"),
        (
            "part: Wing +y, axis: +y, point: [-z, sun], range: [0 deg, 90 deg], "
            "park: {idle: 120 deg}",
            "park angle for 'idle'",
        ),
        ("part: Wing +y, axis: +y", "point"),
        ("part: Wing +y, axis: +y, point: [-z, moon]", "'moon' is not a direction"),
        ("part: Wing +y, axis: +y, point: [-z, sun], speed: 1 deg/s", "speed"),
        ("part: Wing +q, axis: +y, point: [-z, sun]", "no node named 'Wing \\+q'"),
        ("part: Spider, axis: +y, point: [-z, sun]", "2 nodes named 'Spider'"),
        (
            "part: Wing +y, axis: +y, point: [-z, sun], park: {safe: 0 deg}",
            "park names the mode 'safe', which the platform never has",
        ),
        # slew is a mode only when the scenario has slews, and this one has none
        (
            "part: Wing +y, axis: +y, point: [-z, sun], park: {slew: 0 deg}",
            "park names the mode 'slew', which the platform never has",
        ),
    ],
)
def test_a_bad_articulation_stops_the_load(text, data_dir, fields, message):
    with pytest.raises(ValueError, match=message):
        Scenario.from_yaml_text(wing(fields) + text, data_dir)


def test_the_park_angles_go_by_the_platform_mode(text, data_dir):
    # the payload downlinks while the platform is in ttc: downlink parks nothing
    text = text.replace("platform_mode: downlink", "platform_mode: ttc")
    model = wing("part: Wing +y, axis: +y, point: [-z, sun], park: {downlink: 0 deg}")
    with pytest.raises(ValueError, match="'downlink', which the platform never has"):
        Scenario.from_yaml_text(model + text, data_dir)
    model = wing("part: Wing +y, axis: +y, point: [-z, sun], park: {ttc: 0 deg}")
    run = run_scenario(Scenario.from_yaml_text(model + text, data_dir))
    parked = modes_of(run) == "ttc"
    assert parked.any()
    assert np.all(run.articulations["wing"].to_value(u.deg)[parked] == 0)


def test_only_the_designer_skips_the_park_check(text, data_dir):
    # a list being built may not have the parked mode yet
    model = wing("part: Wing +y, axis: +y, point: [-z, sun], park: {safe: 0 deg}")
    with pytest.raises(ValueError, match="park names the mode 'safe'"):
        Scenario.from_yaml_text(model + text, data_dir)
    scenario = Scenario.from_yaml_text(model + text, data_dir, designer=True)
    assert scenario.spacecraft_model is not None
    assert list(scenario.spacecraft_model.articulations["wing"].park) == ["safe"]
    # every other check on the articulations stays
    with pytest.raises(ValueError, match="'moon' is not a direction"):
        moon = wing("part: Wing +y, axis: +y, point: [-z, moon]")
        Scenario.from_yaml_text(moon + text, data_dir, designer=True)


# ---------------------------------------------------------------- The run


def test_without_articulations_there_are_no_angles(run):
    assert run.articulations == {}


def test_each_articulation_has_an_angle_at_each_step(articulated_run):
    angles = articulated_run.articulations
    assert set(angles) == {"wing +y", "wing -y"}
    for values in angles.values():
        assert values.shape == articulated_run.times.shape
        assert np.all(np.abs(values.to_value(u.deg)) <= 180)


def test_a_tracking_wing_faces_the_sun_as_closely_as_its_axis_allows(articulated_run):
    run = articulated_run
    suns = sun_in_body(run)
    tracking = modes_of(run) != "downlink"
    y, minus_z = axis_vector("+y"), axis_vector("-z")
    angles = run.articulations["wing +y"].to_value(u.rad)[tracking]
    face = turned(y, minus_z, angles)
    cosines = np.einsum("ij,ij->i", face, suns[tracking])
    best = np.sqrt(1 - (suns[tracking] @ y) ** 2)
    assert cosines == pytest.approx(best, abs=1e-9)


def test_a_part_can_turn_toward_any_direction_an_attitude_can_use(text, data_dir):
    model = ARTICULATED_MODEL.replace(
        "point: [-z, sun], park: {downlink: 45 deg}", "point: [-z, nadir]"
    )
    run = run_scenario(Scenario.from_yaml_text(model + text + SLEW, data_dir))
    cartesian = run.state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    nadir = -cartesian.xyz.to_value(u.km).T
    nadir /= np.linalg.norm(nadir, axis=1, keepdims=True)
    nadirs = np.einsum("nji,nj->ni", body_rotations(run), nadir)
    y, minus_z = axis_vector("+y"), axis_vector("-z")
    face = turned(y, minus_z, np.asarray(run.articulations["wing +y"].to_value(u.rad)))
    cosines = np.einsum("ij,ij->i", face, nadirs)
    best = np.sqrt(1 - (nadirs @ y) ** 2)
    assert cosines == pytest.approx(best, abs=1e-9)


def test_a_wing_parks_in_its_parking_mode(articulated_run):
    parked = modes_of(articulated_run) == "downlink"
    assert parked.any()
    angles = articulated_run.articulations["wing +y"].to_value(u.deg)
    assert np.all(angles[parked] == 45)


def test_a_wing_can_park_while_the_body_slews(text, data_dir):
    model = ARTICULATED_MODEL.replace(
        "park: {downlink: 45 deg}", "park: {slew: 10 deg}"
    )
    run = run_scenario(Scenario.from_yaml_text(model + text + SLEW, data_dir))
    slewing = modes_of(run) == "slew"
    assert slewing.any()
    angles = np.asarray(run.articulations["wing +y"].to_value(u.deg))
    assert np.all(angles[slewing] == 10)
    assert np.any(angles[~slewing] != 10)


def test_in_sun_pointing_the_wing_angle_is_zero(articulated_run):
    # sun pointing turns -z, the cells' axis, at the sun, so the wing need not
    # turn; each slew ends on the grid's last sun pointing step at the latest
    run = articulated_run
    attitude = labels_at(run.attitude, run.times)
    pointing = (attitude == "sun pointing") & (modes_of(run) != "downlink")
    assert pointing.any()
    angles = run.articulations["wing +y"].to_value(u.deg)
    assert np.abs(angles[pointing]) == pytest.approx(0, abs=1e-6)


def test_a_limited_wing_turns_the_other_way_and_stops_at_its_range(articulated_run):
    run = articulated_run
    suns = sun_in_body(run)
    minus_y, minus_z = axis_vector("-y"), axis_vector("-z")
    free = np.degrees(tracking_angles(minus_y, minus_z, suns))
    limited = run.articulations["wing -y"].to_value(u.deg)
    inside = (free >= -30) & (free <= 60)
    assert inside.any() and (~inside).any()
    assert limited[inside] == pytest.approx(free[inside])
    assert np.all(np.isin(limited[~inside], [-30, 60]))
    # about -y the same sun asks for the opposite angle
    wing = run.articulations["wing +y"].to_value(u.deg)
    tracking = (modes_of(run) != "downlink") & inside & (np.abs(free) < 179)
    assert limited[tracking] == pytest.approx(-wing[tracking], abs=1e-6)


# ---------------------------------------------------------------- The viewer


def test_the_viewer_data_carries_each_articulation(articulated_run, data_dir):
    data = scenario_data(articulated_run)
    joints = data["model"]["articulations"]
    gltf = read_glb_json(data_dir / "spacecraft.glb")
    assert [joint["name"] for joint in joints] == ["wing +y", "wing -y"]
    first = joints[0]
    assert first["part"] == "Wing +y"
    assert first["node"] == node_index(gltf, "Wing +y")
    assert gltf["nodes"][first["node"]]["name"] == "Wing +y"
    assert (first["axis"], first["park_modes"]) == ("+y", ["downlink"])
    assert joints[1]["park_modes"] == []
    angles = articulated_run.articulations["wing +y"].to_value(u.deg)
    assert first["angle_deg"] == pytest.approx(np.round(angles, 3).tolist())


def test_a_model_without_articulations_carries_an_empty_list(articulated_run):
    model = articulated_run.scenario.spacecraft_model
    assert model is not None
    plain = model.model_copy(update={"articulations": {}})
    scenario = articulated_run.scenario.model_copy(update={"spacecraft_model": plain})
    run = dataclasses.replace(articulated_run, scenario=scenario)
    assert scenario_data(run)["model"]["articulations"] == []
