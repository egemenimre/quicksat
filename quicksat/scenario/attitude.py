# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The body's orientation over a run, from the attitudes the activities name, and the slews
between them.

The directions are `nadir`, `sun`, `orbit normal`, `velocity`, `ground velocity` for yaw
steering, and the targets. A slew turns the body into each new attitude before its
activity starts, from the orientation it has then. `docs/scenario/scenario_ref.ipynb`,
under "The attitudes" and "Slews", explains them.

"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np
import portion as P
from astropy.coordinates import (
    CartesianDifferential,
    CartesianRepresentation,
    SkyCoord,
)
from astropy.units import Quantity
from scipy.spatial.transform import Rotation

from quicksat import Q_, u
from quicksat.orbit.attitude import (
    ParallelDirections,
    align,
    axis_vector,
    quaternions,
    rotation_angles,
    turn_between,
)
from quicksat.orbit.geometry import EARTH_ROTATION_RATE, earth_rotations, ground_point
from quicksat.orbit.tle import Tle
from quicksat.orbit.trajectory import Trajectory
from quicksat.scenario.config import Scenario, Slew
from quicksat.scenario.grid import GridOrbit
from quicksat.scenario.names import (
    GROUND_VELOCITY,
    NADIR,
    ORBIT_NORMAL,
    SLEW,
    SUN,
    UNPLANNED,
    VELOCITY,
)
from quicksat.utils.intervals import TimeArray, labels_at, round_time

if TYPE_CHECKING:
    from quicksat.scenario.events import Occurrence
    from quicksat.scenario.run import ScenarioRun

_TURN_TIME_TOLERANCE = Q_(1, "ms")
"""How close two rounds of the turn time must come for the search to stop."""

_MAX_ROUNDS = 10
"""Most rounds of the search for a turn time."""

_PATH_STEP = Q_(10, "s")
"""The longest time between the samples of a slew's target, which fix the way it turns
while the target turns under 18 deg/s."""

TargetOrbits = Mapping[str, Tle | Trajectory | GridOrbit]
"""The orbits of the satellite targets, by name, as the run reads them."""


def directions(
    scenario: Scenario,
    names: set[str],
    state: SkyCoord,
    sun: CartesianRepresentation,
    sat_orbits: TargetOrbits | None = None,
    earth_at: Callable[[TimeArray], np.ndarray] = earth_rotations,
) -> dict[str, np.ndarray]:
    """
    The directions an attitude can use, in GCRS, at each time of a state.

    Parameters
    ----------
    scenario : Scenario
        The scenario, for its targets
    names : set of str
        The directions to work out
    state : SkyCoord
        The satellite's state in GCRS, with its velocities
    sun : CartesianRepresentation
        The sun's positions from the Earth's centre, in GCRS
    sat_orbits : mapping of str to Tle, Trajectory or GridOrbit, optional
        The satellite targets' orbits, by name, for a satellite target
    earth_at : callable, optional
        The Earth's orientation for a `Time` array, by default `earth_rotations`

    Returns
    -------
    directions : dict of str to ndarray
        Each direction, shape (n, 3), of any length

    Raises
    ------
    ValueError
        If a satellite target's orbit is missing
    """
    cartesian = cast(CartesianRepresentation, state.cartesian)
    velocity = cast(CartesianDifferential, cartesian.differentials["s"])
    position = np.atleast_2d(cartesian.xyz.to_value(u.km).T)
    speed = np.atleast_2d(velocity.d_xyz.to_value(u.km / u.s).T)
    found = {
        NADIR: lambda: -position,
        SUN: lambda: np.atleast_2d(sun.xyz.to_value(u.km).T) - position,
        ORBIT_NORMAL: lambda: np.cross(position, speed),
        VELOCITY: lambda: speed,
    }
    out = {name: found[name]() for name in names if name in found}
    for name in names & set(scenario.sat_targets):
        if sat_orbits is None or name not in sat_orbits:
            raise ValueError(f"satellite target '{name}' needs its orbit, from the run")
        other = sat_orbits[name].states(state.obstime, with_velocity=False)
        others = cast(CartesianRepresentation, other.cartesian)
        out[name] = np.atleast_2d(others.xyz.to_value(u.km).T) - position
    earthly = [name for name in names if name not in out]
    if earthly:
        # the Earth's orientation, only where a direction turns with the Earth
        earth = earth_at(state.obstime)
        for name in earthly:
            if name == GROUND_VELOCITY:
                spin = EARTH_ROTATION_RATE.to_value(u.rad / u.s) * earth[:, :, 2]
                out[name] = speed - np.cross(spin, position)
            else:
                target = scenario.gnd_targets[name]
                point = ground_point(target.latitude, target.longitude, target.altitude)
                out[name] = earth @ point - position
    return out


def attitude_rotations(
    scenario: Scenario,
    name: str,
    state: SkyCoord,
    sun: CartesianRepresentation,
    sat_orbits: TargetOrbits | None = None,
    earth_at: Callable[[TimeArray], np.ndarray] = earth_rotations,
) -> np.ndarray:
    """
    The orientation one attitude gives, at each time of a state.

    Parameters
    ----------
    scenario : Scenario
        The scenario, which defines the attitude and the targets
    name : str
        The attitude's name
    state : SkyCoord
        The satellite's state in GCRS, with its velocities
    sun : CartesianRepresentation
        The sun's positions from the Earth's centre, in GCRS
    sat_orbits : mapping of str to Tle, Trajectory or GridOrbit, optional
        The satellite targets' orbits, by name
    earth_at : callable, optional
        The Earth's orientation for a `Time` array, by default `earth_rotations`

    Returns
    -------
    rotations : ndarray
        From body axes into GCRS, shape (n, 3, 3)

    Raises
    ------
    ValueError
        If there is no such attitude, or its fallback is parallel where its constraint
        is too
    """
    attitude = scenario.attitudes.get(name)
    if attitude is None:
        raise ValueError(f"the scenario defines no attitude '{name}'")
    (point_axis, pointed), (constrain_axis, constrained) = (
        attitude.point,
        attitude.constrain,
    )
    fallback = attitude.fallback_direction
    vectors = directions(
        scenario, {pointed, constrained, fallback}, state, sun, sat_orbits, earth_at
    )
    try:
        rotations = align(
            axis_vector(point_axis),
            axis_vector(constrain_axis),
            vectors[pointed],
            vectors[constrained],
            vectors[fallback],
        )
    except ParallelDirections as exc:
        times = cast(TimeArray, state.obstime)
        when = np.atleast_1d(times.utc.isot)[exc.row]
        raise ValueError(f"attitude '{name}' at {when}: {exc}") from exc
    for axis, angle in attitude.offset:
        turn = Rotation.from_rotvec(axis_vector(f"+{axis}") * angle.to_value(u.rad))
        rotations = rotations @ turn.as_matrix()
    return rotations


@dataclass(frozen=True)
class SlewWindow:
    """
    One slew: the body turns into the attitude of the next activity, then settles.

    Parameters
    ----------
    start : Time
        When the turn starts, on the 1 ms grid
    turned : Time
        When the turn ends and settling starts
    end : Time
        When settling ends, at the activity's start unless the run started too late
    angle : Quantity
        The angle turned through
    target : str
        The attitude turned into
    start_rotation : ndarray
        The orientation when the turn starts, shape (3, 3)
    path_seconds : ndarray
        The times of `path`, in s from `start`, shape (n,)
    path : ndarray
        The target's quaternions at those times, with smooth signs, which fix the way of
        the turn, shape (n, 4)
    early : bool
        Whether the turn starts before the activity before it
    into : int
        The place of the occurrence slewed into, in the run's list
    """

    start: TimeArray
    turned: TimeArray
    end: TimeArray
    angle: Quantity
    target: str
    start_rotation: np.ndarray
    path_seconds: np.ndarray
    path: np.ndarray
    early: bool
    into: int

    @property
    def interval(self) -> P.Interval:
        """The slew as a closed-open interval."""
        return P.closedopen(self.start, self.end)

    @property
    def duration(self) -> Quantity:
        """The time from the turn's start to the end of settling, in s."""
        return Q_(round(float((self.end - self.start).to_value(u.s)), 3), "s")


def _attitude_row(occurrences: "list[Occurrence]") -> P.IntervalDict:
    """The attitude of the activity under way at each time, without slews."""
    row = P.IntervalDict()
    for occurrence in occurrences:
        row[occurrence.interval] = occurrence.activity.attitude
    return row


def plan_slews(
    occurrences: "list[Occurrence]",
    slew: Slew,
    scenario: Scenario,
    interval: P.Interval,
    state_at: Callable[[TimeArray], SkyCoord],
    sun_at: Callable[[TimeArray], CartesianRepresentation],
    sat_orbits: TargetOrbits | None = None,
    earth_at: Callable[[TimeArray], np.ndarray] = earth_rotations,
) -> list[SlewWindow]:
    """
    Plan the slew into each activity whose attitude differs from the one before, in time
    order.

    Each ends, with its settling, as its activity starts. A slew that must start before
    an earlier one drops the earlier one.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences, in time order
    slew : Slew
        The rate, acceleration and settling time
    scenario : Scenario
        The scenario, which defines the attitudes
    interval : portion.Interval
        The run, before which no slew starts
    state_at : callable
        The satellite's state in GCRS, with velocities, for a `Time` array
    sun_at : callable
        The sun's position in GCRS for a `Time` array
    sat_orbits : mapping of str to Tle, Trajectory or GridOrbit, optional
        The satellite targets' orbits, by name
    earth_at : callable, optional
        The Earth's orientation for a `Time` array, by default `earth_rotations`

    Returns
    -------
    slews : list of SlewWindow
        The slews, in time order
    """
    row = _attitude_row(occurrences)
    run_start: TimeArray = interval.lower
    windows: list[SlewWindow] = []

    def rotations_of(name: str, times: TimeArray) -> np.ndarray:
        return attitude_rotations(
            scenario, name, state_at(times), sun_at(times), sat_orbits, earth_at
        )

    def rotation_of(name: str, time: TimeArray) -> np.ndarray:
        return rotations_of(name, time + Q_(np.zeros(1), "s"))[0]

    def orientation_at(time: TimeArray) -> np.ndarray:
        # the latest slew under way wins, as it starts from the one before
        for window in reversed(windows):
            if window.start <= time < window.end:
                target = rotation_of(window.target, time)[None]
                return _slew_rotations(window, slew, time, target)[0]
        return rotation_of(cast(str, row[time]), time)

    previous = None
    for index, occurrence in enumerate(occurrences):
        if occurrence.negative_duration:
            continue
        if (
            previous is not None
            and occurrence.activity.attitude != previous.activity.attitude
        ):
            start, turned, angle = _turn(
                occurrence.activity.attitude,
                occurrence.start,
                slew,
                run_start,
                orientation_at,
                rotation_of,
            )
            # a slew that cannot start early enough runs on into its activity
            end = max(occurrence.start, round_time(turned + slew.settling_time))
            start_rotation = orientation_at(start)
            path_seconds, path = _target_path(
                start,
                turned,
                start_rotation,
                lambda times, name=occurrence.activity.attitude: rotations_of(
                    name, times
                ),
            )
            window = SlewWindow(
                start=start,
                turned=turned,
                end=end,
                angle=angle,
                target=occurrence.activity.attitude,
                start_rotation=start_rotation,
                path_seconds=path_seconds,
                path=path,
                early=bool(start < previous.start) or bool(end > occurrence.start),
                into=index,
            )
            # the body turns from where it was before these slews, so it never
            # makes them
            while windows and windows[-1].start >= start:
                windows.pop()
            windows.append(window)
        previous = occurrence
    return windows


def _turn(
    target: str,
    end: TimeArray,
    slew: Slew,
    run_start: TimeArray,
    orientation_at: Callable[[TimeArray], np.ndarray],
    rotation_of: Callable[[str, TimeArray], np.ndarray],
) -> tuple[TimeArray, TimeArray, Quantity]:
    """
    When a turn into an attitude starts and ends, on the 1 ms grid, and its angle in
    degrees, by rounds of guess and correct, or by bisection in an earlier slew.
    """
    turned = round_time(end - slew.settling_time)
    goal = rotation_of(target, turned)

    def angle_from(start: TimeArray) -> Quantity:
        angle = rotation_angles(orientation_at(start), goal)[0]
        return Q_(angle, "rad").to(u.deg)

    def overrun(start: TimeArray) -> float:
        # how long after `turned` a turn from `start` would end, in seconds
        late = float((start - turned).to_value(u.s))
        return late + slew.turn_time(angle_from(start)).to(u.s).value

    turn = slew.turn_time(angle_from(turned))
    for _ in range(_MAX_ROUNDS):
        start = round_time(turned - turn)
        if start < run_start:
            break
        new_turn = slew.turn_time(angle_from(start))
        if abs(new_turn - turn) < _TURN_TIME_TOLERANCE:
            return start, turned, angle_from(start)
        turn = new_turn

    low = max(run_start, round_time(turned - slew.turn_time(Q_(180, "deg"))))
    if overrun(low) > 0:
        # even the earliest start is too late: start with the run, and end late
        angle = angle_from(low)
        return low, round_time(low + slew.turn_time(angle)), angle
    high = turned
    tolerance = _TURN_TIME_TOLERANCE.to(u.s).value
    while float((high - low).to_value(u.s)) > tolerance:
        middle = low + (high - low) / 2
        if overrun(middle) > 0:
            high = middle
        else:
            low = middle
    start = round_time(low)
    return start, turned, angle_from(start)


def _target_path(
    start: TimeArray,
    turned: TimeArray,
    start_rotation: np.ndarray,
    rotations_of: Callable[[TimeArray], np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """
    The target attitude's quaternions sampled through a turn, with signs kept smooth and
    the last nearer the start, so the body never jumps.
    """
    length = float((turned - start).to_value(u.s))
    count = int(np.ceil(length / _PATH_STEP.to(u.s).value)) + 1
    seconds = np.linspace(0.0, length, count)
    path = quaternions(rotations_of(start + Q_(seconds, "s")))
    if path[-1] @ Rotation.from_matrix(start_rotation).as_quat() < 0:
        path = -path
    return seconds, path


def _slew_rotations(
    window: SlewWindow, slew: Slew, times: TimeArray, targets: np.ndarray
) -> np.ndarray:
    """
    The orientation at times inside a slew: partway to the moving target in the turn,
    then the target while settling.
    """
    seconds = np.atleast_1d((times - window.start).to_value(u.s))
    fractions = slew.turned(window.angle, Q_(seconds, "s"))
    # each time takes the sign of the nearest sample of the target's path
    nearest = np.interp(seconds, window.path_seconds, np.arange(len(window.path)))
    toward = window.path[np.rint(nearest).astype(int)]
    return turn_between(window.start_rotation, targets, fractions, toward=toward)


def _activity_attitudes(run: "ScenarioRun") -> np.ndarray:
    """
    The attitude of the activity under way at each time of the grid, without slews, and
    `unplanned` after the last.
    """
    row = _attitude_row(run.occurrences)
    unplanned = run.unplanned
    row[unplanned] = UNPLANNED
    names = labels_at(row, run.times)
    # the run is open at its end, so the last time takes the value before the end
    names[-1] = run.occurrences[-1].activity.attitude if unplanned.empty else UNPLANNED
    return names


def body_rotations(run: "ScenarioRun") -> np.ndarray:
    """
    The body's orientation at each time of the run's grid, slews included.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    rotations : ndarray
        From body axes into GCRS, shape (n, 3, 3), NaN where the run is `unplanned`
    """
    attitude = _activity_attitudes(run)

    def state_at(rows: np.ndarray) -> tuple[SkyCoord, CartesianRepresentation]:
        sun = cast(CartesianRepresentation, run.sun[rows])
        return cast(SkyCoord, run.state[rows]), sun

    rotations = np.full((len(run.times), 3, 3), np.nan)
    for name in set(attitude) - {UNPLANNED}:
        rows = attitude == name
        rotations[rows] = attitude_rotations(
            run.scenario, name, *state_at(rows), run.grid.targets, run.grid.earth
        )
    slew = run.scenario.slew
    if slew is not None:
        # in time order, so a slew that starts partway through another wins
        for window in run.slews:
            rows = (run.times >= window.start) & (run.times < window.end)
            if rows.any():
                targets = attitude_rotations(
                    run.scenario,
                    window.target,
                    *state_at(rows),
                    run.grid.targets,
                    run.grid.earth,
                )
                rotations[rows] = _slew_rotations(
                    window, slew, run.times[rows], targets
                )
    return rotations


def attitude_names(run: "ScenarioRun") -> np.ndarray:
    """
    The attitude in effect at each time of the run's grid, as `body_rotations` turns the
    body.

    Parameters
    ----------
    run : ScenarioRun
        The run

    Returns
    -------
    names : ndarray
        The attitudes, as objects, with `slew` and `unplanned`
    """
    names = _activity_attitudes(run)
    for window in run.slews:
        names[(run.times >= window.start) & (run.times < window.end)] = SLEW
    return names
