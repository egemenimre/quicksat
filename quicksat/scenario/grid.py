# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The run's grid, and the values between its steps.

A run works out the orbits, the sun and the Earth's orientation on its time grid.
The searches that follow, for the shadow edges, the latitude crossings, the
targets' rise and set, and the slews, ask for them again at a few times between
the steps, hundreds of times over. Worked out in full, each request goes through
SGP4 and astropy's frames, and takes about 10 ms however few the times are.
`RunGrid` answers from splines through the grid instead, in well under 1 ms.

- **The satellite:** splines of degree 7 through its positions and velocities.
  In low orbit, they are good to 5 micrometres at a step of 10 s, and to 1 cm at
  120 s. The error then grows fast, to 10 m at 300 s. So above
  `SPLINE_STEP_LIMIT`, each request is worked out in full. An orbit read from a
  trajectory file is always used as it is: its own splines keep each manoeuvre
  apart, and splines through the grid would smooth it.
- **A satellite target:** the same, through its positions alone, since the
  attitudes and the line of sight need no more. Working out its velocities on
  the grid would take five times as long.
- **The sun:** a spline of degree 7 through its positions, good to 1 cm.
- **The Earth's orientation:** the rotations from ITRS into GCRS, interpolated
  along the shortest turn between two steps, good to 1e-11 deg.

Degree 7 is the lowest that reaches 1 cm at a step of 120 s. Hermite splines,
through the positions and the velocities together, do worse here. SGP4's
velocities, once astropy turns them into GCRS, differ from the slope of its
positions by about 24 mm/s, and a Hermite spline is bent to meet both.

A time outside the grid is always worked out in full.

"""

from typing import cast

import numpy as np
from astropy.coordinates import (
    GCRS,
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from scipy.interpolate import BSpline, make_interp_spline
from scipy.spatial.transform import Rotation, Slerp

from quicksat import Q_, u
from quicksat.orbit.geometry import earth_rotations, sun_positions
from quicksat.orbit.tle import Tle
from quicksat.orbit.trajectory import Trajectory
from quicksat.utils.intervals import TimeArray

SPLINE_DEGREE = 7
"""Degree of the splines through the grid."""

SPLINE_STEP_LIMIT = Q_(120, "s")
"""The longest step at which the orbits come from the splines through the grid."""


class _Grid:
    """
    The grid's times, as seconds from its first.

    Parameters
    ----------
    times : Time
        The grid, in order
    """

    def __init__(self, times: TimeArray):
        self.epoch: TimeArray = times[0]
        self.offsets = np.atleast_1d((times - self.epoch).to_value(u.s))

    def inside(self, times: TimeArray) -> np.ndarray | None:
        """
        The times as seconds from the grid's first, if all of them lie on it.

        Parameters
        ----------
        times : Time
            The times

        Returns
        -------
        offsets : ndarray or None
            In seconds, or None if a time lies outside the grid
        """
        offsets = np.atleast_1d((times - self.epoch).to_value(u.s))
        if offsets.min() < self.offsets[0] or offsets.max() > self.offsets[-1]:
            return None
        return offsets


class GridOrbit:
    """
    An orbit read from splines through its states on the run's grid.

    A time outside the grid goes to the orbit's own source, and so does every
    time when the splines would not be good to 1 cm. Velocities come from the
    splines only if the states on the grid have them.

    Parameters
    ----------
    source : Tle or Trajectory
        Where the states come from
    times : Time
        The grid
    state : SkyCoord
        The states on the grid, in GCRS, with or without velocities
    """

    def __init__(self, source: Tle | Trajectory, times: TimeArray, state: SkyCoord):
        self.source = source
        self._grid = _Grid(times)
        steps = np.diff(self._grid.offsets)
        self._splined = (
            not isinstance(source, Trajectory)
            and len(steps) >= SPLINE_DEGREE
            and steps.max() <= SPLINE_STEP_LIMIT.to_value(u.s)
        )
        self._position: BSpline | None = None
        self._velocity: BSpline | None = None
        if self._splined:
            cartesian = cast(CartesianRepresentation, state.cartesian)
            offsets = self._grid.offsets
            self._position = make_interp_spline(
                offsets, cartesian.xyz.to_value(u.km).T, k=SPLINE_DEGREE
            )
            velocity = cartesian.differentials.get("s")
            if velocity is not None:
                d_xyz = cast(CartesianDifferential, velocity).d_xyz
                self._velocity = make_interp_spline(
                    offsets, d_xyz.to_value(u.km / u.s).T, k=SPLINE_DEGREE
                )

    def states(self, times: TimeArray, with_velocity: bool = True) -> SkyCoord:
        """
        The states at any times, in GCRS, as the source would give them.

        Parameters
        ----------
        times : Time
            The times, as an array
        with_velocity : bool, optional
            Whether the state carries velocities as well as positions. True by
            default.

        Returns
        -------
        state : SkyCoord
            The position relative to the centre of the Earth, and the velocity if
            asked for, in GCRS. Its `obstime` is `times`.
        """
        offsets = self._grid.inside(times) if self._position is not None else None
        if offsets is None or (with_velocity and self._velocity is None):
            return self.source.states(times, with_velocity=with_velocity)
        assert self._position is not None
        data = CartesianRepresentation(Q_(self._position(offsets).T, "km"))
        if with_velocity:
            assert self._velocity is not None
            speeds = Q_(self._velocity(offsets).T, "km/s")
            data = data.with_differentials(CartesianDifferential(speeds))
        return SkyCoord(GCRS(data, obstime=times))


class RunGrid:
    """
    The run's grid, with splines through it for the times between its steps.

    Parameters
    ----------
    times : Time
        The grid, in order
    orbit : Tle or Trajectory
        The satellite's orbit
    state : SkyCoord
        The satellite's states on the grid, in GCRS, with velocities
    sun : CartesianRepresentation
        The sun's positions on the grid, in GCRS, in km
    sat_orbits : dict of str to Tle or Trajectory
        The satellite targets' orbits, by name
    sat_states : dict of str to SkyCoord
        The satellite targets' positions on the grid, in GCRS, by name

    Attributes
    ----------
    satellite : GridOrbit
        The satellite's orbit
    targets : dict of str to GridOrbit
        Each satellite target's orbit, by name
    earth_rotations : ndarray
        The Earth's orientation on the grid, from `earth_rotations`, shape
        (n, 3, 3)
    """

    def __init__(
        self,
        times: TimeArray,
        orbit: Tle | Trajectory,
        state: SkyCoord,
        sun: CartesianRepresentation,
        sat_orbits: dict[str, Tle | Trajectory],
        sat_states: dict[str, SkyCoord],
    ):
        self._grid = _Grid(times)
        offsets = self._grid.offsets
        self.satellite = GridOrbit(orbit, times, state)
        self.targets = {
            name: GridOrbit(source, times, sat_states[name])
            for name, source in sat_orbits.items()
        }
        self._sun = make_interp_spline(
            offsets, sun.xyz.to_value(u.km).T, k=min(SPLINE_DEGREE, len(offsets) - 1)
        )
        self.earth_rotations = earth_rotations(times)
        self._earth = Slerp(offsets, Rotation.from_matrix(self.earth_rotations))

    def sun(self, times: TimeArray) -> CartesianRepresentation:
        """
        The sun's position at any times, as `sun_positions` gives it.

        Parameters
        ----------
        times : Time
            The times, as an array

        Returns
        -------
        sun : CartesianRepresentation
            Relative to the centre of the Earth, in GCRS, in km
        """
        offsets = self._grid.inside(times)
        if offsets is None:
            return sun_positions(times)
        return CartesianRepresentation(Q_(self._sun(offsets).T, "km"))

    def earth(self, times: TimeArray) -> np.ndarray:
        """
        The Earth's orientation at any times, as `earth_rotations` gives it.

        Parameters
        ----------
        times : Time
            The times, as an array

        Returns
        -------
        rotations : ndarray
            Matrices that turn ITRS vectors into GCRS, shape (n, 3, 3)
        """
        offsets = self._grid.inside(times)
        if offsets is None:
            return earth_rotations(times)
        return self._earth(offsets).as_matrix()
