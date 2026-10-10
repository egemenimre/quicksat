# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the body's orientation over a run.

The fixture's attitudes are nadir with `+z` at the nadir and `-y` along the orbit
normal, and sun pointing with `-z` at the sun and `-y` kept along the orbit
normal. Each step is checked against the directions worked out from the state.

`named_run` flies one orbit of the fixture's orbit through three more attitudes:
a roll offset, a ground target, and yaw steering on the ground velocity.
"""

import numpy as np
import pytest
from astropy.coordinates import (
    GCRS,
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.time import Time

from quicksat import u
from quicksat.orbit.attitude import axis_vector
from quicksat.orbit.geometry import earth_rotations, ground_point
from quicksat.scenario.attitude import attitude_rotations, body_rotations, directions
from quicksat.scenario.config import Scenario
from quicksat.scenario.run import run_scenario
from quicksat.utils.intervals import labels_at


def unit(vectors):
    """Vectors scaled to unit length."""
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


@pytest.fixture(scope="module")
def pointing(run):
    """The rotations, the attitude at each step, and the reference directions."""
    rotations = body_rotations(run)
    attitude = labels_at(run.attitude, run.times)
    attitude[-1] = run.occurrences[-1].activity.attitude
    cartesian = run.state.cartesian
    position = cartesian.xyz.to_value(u.km).T
    velocity = cartesian.differentials["s"].d_xyz.to_value(u.km / u.s).T
    directions = {
        "nadir": unit(-position),
        "normal": unit(np.cross(position, velocity)),
        "sun": unit(run.sun.xyz.to_value(u.km).T - position),
        "velocity": unit(velocity),
    }
    return rotations, attitude, directions


def axis_in_gcrs(rotations, axis):
    """Where a body axis points, in GCRS, at each step."""
    return rotations @ axis_vector(axis)


def test_every_step_has_a_proper_rotation(pointing):
    rotations, attitude, _ = pointing
    assert set(attitude) == {"nadir", "sun pointing"}
    assert np.allclose(
        rotations @ np.transpose(rotations, (0, 2, 1)), np.eye(3), atol=1e-12
    )
    assert np.allclose(np.linalg.det(rotations), 1.0, atol=1e-12)


def test_nadir_points_its_axes_as_set(pointing):
    rotations, attitude, directions = pointing
    rows = attitude == "nadir"
    assert np.allclose(
        axis_in_gcrs(rotations[rows], "+z"), directions["nadir"][rows], atol=1e-12
    )
    assert np.allclose(
        axis_in_gcrs(rotations[rows], "-y"), directions["normal"][rows], atol=1e-12
    )


def test_nadir_with_these_axes_is_lvlh(pointing):
    # x then runs along the track, within the small angle of a near-circular orbit
    rotations, attitude, directions = pointing
    rows = attitude == "nadir"
    cosine = np.sum(
        axis_in_gcrs(rotations[rows], "+x") * directions["velocity"][rows], axis=1
    )
    assert np.degrees(np.arccos(np.clip(cosine, -1, 1))).max() < 0.1


def test_sun_pointing_points_its_axes_as_set(pointing):
    rotations, attitude, directions = pointing
    rows = attitude == "sun pointing"
    sun, normal = directions["sun"][rows], directions["normal"][rows]
    across = unit(normal - np.sum(normal * sun, axis=1, keepdims=True) * sun)
    assert np.allclose(axis_in_gcrs(rotations[rows], "-z"), sun, atol=1e-12)
    assert np.allclose(axis_in_gcrs(rotations[rows], "-y"), across, atol=1e-12)


# ---------------------------------------------------------------- Named attitudes

NAMED = """
orbit: {tle_file: sso_510km.tle}
start: 2026-10-01T00:00:00
duration: 90 min
targets:
  Toulouse: {latitude: 43.6 deg, longitude: 1.44 deg, altitude: 150 m}
attitudes:
  roll 30: {point: [+z, nadir], constrain: [-y, orbit normal], offset: [x 30 deg]}
  track Toulouse: {point: [+z, Toulouse], constrain: [-y, orbit normal]}
  yaw steering: {point: [+z, nadir], constrain: [+x, ground velocity]}
activities:
  - [30 min, roll 30, idle]
  - [30 min, track Toulouse, imaging]
  - [30 min, yaw steering, imaging]
"""
"""Three attitudes beyond the fixture's two, each flown for 30 min."""


@pytest.fixture(scope="module")
def named_run(data_dir):
    """One orbit through the three attitudes of `NAMED`."""
    return run_scenario(Scenario.from_yaml_text(NAMED, data_dir))


def steps_of(run, name):
    """The rotations, positions and velocities of the steps in one attitude."""
    attitude = labels_at(run.attitude, run.times)
    attitude[-1] = run.occurrences[-1].activity.attitude
    rows = attitude == name
    cartesian = run.state.cartesian
    position = cartesian.xyz.to_value(u.km).T[rows]
    velocity = cartesian.differentials["s"].d_xyz.to_value(u.km / u.s).T[rows]
    return body_rotations(run)[rows], position, velocity, rows


def test_a_roll_offset_turns_the_nadir_attitude_about_x(named_run):
    rotations, position, velocity, _ = steps_of(named_run, "roll 30")
    z = axis_in_gcrs(rotations, "+z")
    nadir, normal = unit(-position), unit(np.cross(position, velocity))
    # turned right-handed about x, +z leans from nadir toward the orbit normal
    assert np.sum(z * nadir, axis=1) == pytest.approx(np.cos(np.radians(30)))
    assert np.sum(z * normal, axis=1) == pytest.approx(0.5)
    # x, the axis of the turn, stays where nadir pointing puts it
    across = unit(np.cross(nadir, normal))
    assert np.allclose(axis_in_gcrs(rotations, "+x"), across, atol=1e-12)


def test_a_target_attitude_points_its_axis_through_the_target(named_run):
    rotations, position, _, rows = steps_of(named_run, "track Toulouse")
    target = named_run.scenario.targets["Toulouse"]
    point = ground_point(target.latitude, target.longitude, target.altitude)
    toward = unit(earth_rotations(named_run.times[rows]) @ point - position)
    assert np.allclose(axis_in_gcrs(rotations, "+z"), toward, atol=1e-12)


def test_yaw_steering_keeps_x_along_the_ground_velocity(named_run):
    rotations, position, _, rows = steps_of(named_run, "yaw steering")
    nadir = unit(-position)
    state = named_run.state[rows]
    ground = directions(named_run.scenario, {"ground velocity"}, state, named_run.sun)
    flat = ground["ground velocity"]
    flat = unit(flat - np.sum(flat * nadir, axis=1, keepdims=True) * nadir)
    assert np.allclose(axis_in_gcrs(rotations, "+z"), nadir, atol=1e-12)
    assert np.allclose(axis_in_gcrs(rotations, "+x"), flat, atol=1e-12)


def test_the_ground_velocity_yaw_falls_from_the_equator_to_the_turn(run):
    # for a 500 km sun-synchronous orbit: 3.71 deg at the equator, 2.62 deg at 45
    # deg of latitude, and none at the highest latitude, where the track runs
    # east to west. The fixture's orbit is at 510 km, which changes these little.
    found = directions(
        run.scenario, {"nadir", "velocity", "ground velocity"}, run.state, run.sun
    )
    nadir = unit(found["nadir"])

    def flat(vectors):
        return unit(vectors - np.sum(vectors * nadir, axis=1, keepdims=True) * nadir)

    cosine = np.sum(flat(found["velocity"]) * flat(found["ground velocity"]), axis=1)
    yaw = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
    latitude = np.abs(run.latitude.to_value(u.deg))
    assert yaw[latitude.argmin()] == pytest.approx(3.71, abs=0.05)
    assert yaw[np.abs(latitude - 45).argmin()] == pytest.approx(2.62, abs=0.08)
    assert yaw[latitude.argmax()] < 0.2


def test_parallel_fallback_directions_name_the_attitude_and_the_time(data_dir):
    # velocity straight down, and the sun straight below: nothing fixes the turn
    text = NAMED.replace(
        "  roll 30:",
        "  stuck: {point: [+z, nadir], constrain: [+x, velocity], fallback: sun}\n"
        "  roll 30:",
    )
    scenario = Scenario.from_yaml_text(text, data_dir)
    position = CartesianRepresentation([7000.0], [0.0], [0.0], unit=u.km)
    falling = CartesianDifferential([-7.0], [0.0], [0.0], unit=u.km / u.s)
    when = Time(["2026-10-01T00:00:00"], scale="utc")
    state = SkyCoord(position.with_differentials(falling), frame=GCRS(obstime=when))
    sun = CartesianRepresentation([-1.5e8], [0.0], [0.0], unit=u.km)
    with pytest.raises(ValueError, match="attitude 'stuck' at 2026-10-01T00:00:00"):
        attitude_rotations(scenario, "stuck", state, sun)
