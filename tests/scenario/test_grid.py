# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Tests for the run's grid, and the values between its steps.

`run` steps every 10 s. Between the steps, the splines must give what SGP4, the
sun and the Earth's orientation give in full, and a time the splines do not
serve must go to the source.
"""

import numpy as np
from astropy.coordinates import CartesianDifferential, CartesianRepresentation
from scipy.spatial.transform import Rotation

from quicksat import Q_, u
from quicksat.orbit.geometry import earth_rotations, sun_positions
from quicksat.orbit.trajectory import Trajectory
from quicksat.scenario.grid import GridOrbit


def between(run):
    """Times between the grid's steps, 3.7 s after each of the first 300."""
    return run.times[:300] + Q_(3.7, "s")


def km(state):
    """A state's positions [km], one row each."""
    cartesian = state.cartesian
    assert isinstance(cartesian, CartesianRepresentation)
    return cartesian.xyz.to_value(u.km).T


def km_s(state):
    """A state's velocities [km/s], one row each."""
    velocity = state.cartesian.differentials["s"]
    assert isinstance(velocity, CartesianDifferential)
    return velocity.d_xyz.to_value(u.km / u.s).T


def test_between_the_steps_the_satellite_is_where_sgp4_puts_it(run):
    times = between(run)
    found, exact = run.grid.satellite.states(times), run.orbit.states(times)
    # within 1 mm and 1 mm/s
    assert np.abs(km(found) - km(exact)).max() < 1e-6
    assert np.abs(km_s(found) - km_s(exact)).max() < 1e-6


def test_between_the_steps_the_sun_and_the_earth_match_astropy(run):
    times = between(run)
    sun = run.grid.sun(times).xyz.to_value(u.km)
    assert np.abs(sun - sun_positions(times).xyz.to_value(u.km)).max() < 1e-4
    turns = Rotation.from_matrix(run.grid.earth(times)).inv() * Rotation.from_matrix(
        earth_rotations(times)
    )
    assert turns.magnitude().max() < 1e-10
    # on the steps, the Earth's orientation is the one the grid holds
    np.testing.assert_allclose(
        run.grid.earth(run.times), run.grid.earth_rotations, atol=1e-14
    )


def test_a_target_splines_its_positions_alone(run):
    # a target's states on the grid come without velocities: the splines give
    # positions, and a state with velocities goes to the source
    orbit = GridOrbit(run.orbit, run.times, run.orbit.states(run.times, False))
    times = between(run)
    found = orbit.states(times, with_velocity=False)
    exact = run.orbit.states(times, with_velocity=False)
    assert np.abs(km(found) - km(exact)).max() < 1e-6
    speeds = km_s(orbit.states(times))
    np.testing.assert_array_equal(speeds, km_s(run.orbit.states(times)))


def test_a_time_outside_the_grid_is_worked_out_in_full(run):
    times = run.times[-1] + Q_([0.0, 30.0], "s")
    found, exact = run.grid.satellite.states(times), run.orbit.states(times)
    np.testing.assert_array_equal(km(found), km(exact))
    np.testing.assert_array_equal(km_s(found), km_s(exact))
    np.testing.assert_array_equal(run.grid.earth(times), earth_rotations(times))
    np.testing.assert_array_equal(
        run.grid.sun(times).xyz.value, sun_positions(times).xyz.value
    )


def test_on_a_long_step_the_orbit_is_worked_out_in_full(run):
    # at 300 s, the splines would be 10 m out
    times = run.times[0] + Q_(np.arange(0.0, 6000.0, 300.0), "s")
    orbit = GridOrbit(run.orbit, times, run.orbit.states(times))
    middle = times[:-1] + Q_(150.0, "s")
    np.testing.assert_array_equal(
        km(orbit.states(middle)), km(run.orbit.states(middle))
    )


def test_a_trajectory_is_used_as_it_is(run):
    # its own splines keep a manoeuvre apart, which splines through the grid
    # would smooth
    trajectory = Trajectory.from_states(run.state)
    orbit = GridOrbit(trajectory, run.times, run.state)
    times = between(run)
    found, exact = orbit.states(times), trajectory.states(times)
    np.testing.assert_array_equal(km(found), km(exact))
    np.testing.assert_array_equal(km_s(found), km_s(exact))
