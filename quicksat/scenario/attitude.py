# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The body's orientation over a run, from the attitudes the activities name.

Each attitude fixes one body axis on a direction, and turns a second body axis
as close as it can get to another direction. The directions, at each step:

- `nadir`: toward the centre of the Earth.
- `sun`: toward the sun, as seen from the satellite.
- `orbit normal`: the position crossed with the velocity.
- `velocity`: the inertial velocity.
- `ground velocity`: the velocity relative to the turning Earth, v - w x r. An
  attitude with `+z` at nadir and `+x` toward it steers in yaw, so that a
  detector's lines stay across the motion of the ground below.
- a ground point from the scenario's `targets`: from the satellite to the point,
  which turns with the Earth.

Where the second direction is parallel to the first, it no longer fixes the turn
about the first axis. The attitude's fallback direction then takes its place. An
example is sun pointing with the orbit normal as its second direction, at a beta
of +-90 degrees. After that, the attitude's offset turns, if any, are applied in
order, each about a body axis.

Without a `slew` block in the scenario, attitude changes are instant. With one,
the body turns into each new attitude before the activity that needs it starts,
so the turn takes the end of the activity before. The turn starts from the
orientation the body has then, and ends in the new attitude as it is when the
turn ends. Its time follows from the angle between the two, with the scenario's
rate and acceleration. The body then settles in the new attitude until the
activity starts.

"""

from collections.abc import Callable
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
    rotation_angles,
    turn_between,
)
from quicksat.orbit.geometry import EARTH_ROTATION_RATE, earth_rotations, ground_point
from quicksat.scenario.config import (
    GROUND_VELOCITY,
    NADIR,
    ORBIT_NORMAL,
    SUN,
    VELOCITY,
    Scenario,
    Slew,
)
from quicksat.utils.intervals import TimeArray, labels_at, round_time

if TYPE_CHECKING:
    from quicksat.scenario.run import Occurrence, ScenarioRun

_TURN_TIME_TOLERANCE = Q_(1, "ms")
"""How close two rounds of the turn time must come for the search to stop."""

_MAX_ROUNDS = 10
"""Most rounds of the search for a turn time."""


def directions(
    scenario: Scenario, names: set[str], state: SkyCoord, sun: CartesianRepresentation
) -> dict[str, np.ndarray]:
    """
    The directions an attitude can use, in GCRS, at each time of a state.

    Parameters
    ----------
    scenario : Scenario
        The scenario, for its ground targets
    names : set of str
        The directions to work out: built-in ones and target names
    state : SkyCoord
        The satellite's state in GCRS, with its velocities
    sun : CartesianRepresentation
        Positions of the sun relative to the centre of the Earth, in GCRS

    Returns
    -------
    directions : dict of str to ndarray
        Each direction asked for, shape (n, 3), not of unit length
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
    earthly = [name for name in names if name not in found]
    if earthly:
        # the Earth's orientation, only where a direction turns with the Earth
        earth = earth_rotations(state.obstime)
        for name in earthly:
            if name == GROUND_VELOCITY:
                spin = EARTH_ROTATION_RATE.to_value(u.rad / u.s) * earth[:, :, 2]
                out[name] = speed - np.cross(spin, position)
            else:
                target = scenario.targets[name]
                point = ground_point(target.latitude, target.longitude, target.altitude)
                out[name] = earth @ point - position
    return out


def attitude_rotations(
    scenario: Scenario, name: str, state: SkyCoord, sun: CartesianRepresentation
) -> np.ndarray:
    """
    The orientation one attitude gives, at each time of a state.

    Parameters
    ----------
    scenario : Scenario
        The scenario, which defines the attitude and any ground targets
    name : str
        The attitude's name
    state : SkyCoord
        The satellite's state in GCRS, with its velocities
    sun : CartesianRepresentation
        Positions of the sun relative to the centre of the Earth, in GCRS

    Returns
    -------
    rotations : ndarray
        Matrices that turn body vectors into GCRS, shape (n, 3, 3). Column i is
        body axis i, seen in GCRS.

    Raises
    ------
    ValueError
        If the scenario defines no such attitude, or if its fallback direction is
        parallel to its pointed one where its constraint's is too
    """
    attitude = scenario.attitudes.get(name)
    if attitude is None:
        raise ValueError(f"the scenario defines no attitude '{name}'")
    (point_axis, pointed), (constrain_axis, constrained) = (
        attitude.point,
        attitude.constrain,
    )
    fallback = attitude.fallback_direction
    vectors = directions(scenario, {pointed, constrained, fallback}, state, sun)
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
    One slew: the body turns into the attitude of the next activity.

    Parameters
    ----------
    start : Time
        When the turn starts, on the 1 ms grid
    turned : Time
        When the turn ends and the body starts to settle
    end : Time
        When settling ends. It is when the activity starts, unless the run
        started too late for the slew to fit before it.
    angle : Quantity
        The angle the body turns through
    target : str
        The attitude turned into
    start_rotation : ndarray
        The orientation when the turn starts, shape (3, 3)
    end_rotation : ndarray
        The target attitude's orientation when the turn ends, shape (3, 3). It
        fixes which way the body turns.
    early : bool
        True if the turn starts before the activity before it does, because that
        activity is shorter than the slew
    into : int
        The place of the occurrence slewed into, in the run's list
    """

    start: TimeArray
    turned: TimeArray
    end: TimeArray
    angle: Quantity
    target: str
    start_rotation: np.ndarray
    end_rotation: np.ndarray
    early: bool
    into: int

    @property
    def interval(self) -> P.Interval:
        """
        The slew as a time interval, closed at its start and open at its end.

        Returns
        -------
        interval : portion.Interval
        """
        return P.closedopen(self.start, self.end)

    @property
    def duration(self) -> Quantity:
        """
        The time from the start of the turn to the end of settling.

        Returns
        -------
        duration : Quantity
            In seconds
        """
        return Q_(round(float((self.end - self.start).to_value(u.s)), 3), "s")


def _attitude_row(occurrences: "list[Occurrence]") -> P.IntervalDict:
    """
    The attitude of the activity under way at each time, without slews.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences of the run

    Returns
    -------
    row : portion.IntervalDict
        Time intervals mapped to attitude names
    """
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
) -> list[SlewWindow]:
    """
    Plan the slew into each activity whose attitude differs from the one before.

    The slews are planned in time order. Each one ends, with its settling, as its
    activity starts. Its turn starts from the orientation the body has then,
    which can be partway through an earlier slew. The turn time depends on the
    angle, and the angle on when the turn starts, so the two are found in turn
    until the time settles to 1 ms. An activity with a negative duration takes no
    time, so it is passed over.

    Parameters
    ----------
    occurrences : list of Occurrence
        The occurrences of the run, in time order
    slew : Slew
        The rate, acceleration and settling time
    scenario : Scenario
        The scenario, which defines the attitudes
    interval : portion.Interval
        The run. No slew starts before it.
    state_at : callable
        Gives the satellite's state in GCRS, with velocities, for a `Time` array
    sun_at : callable
        Gives the position of the sun in GCRS for a `Time` array

    Returns
    -------
    slews : list of SlewWindow
        The slews, in time order
    """
    row = _attitude_row(occurrences)
    run_start: TimeArray = interval.lower
    windows: list[SlewWindow] = []

    def rotation_of(name: str, time: TimeArray) -> np.ndarray:
        times = time + Q_(np.zeros(1), "s")
        return attitude_rotations(scenario, name, state_at(times), sun_at(times))[0]

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
            windows.append(
                SlewWindow(
                    start=start,
                    turned=turned,
                    end=end,
                    angle=angle,
                    target=occurrence.activity.attitude,
                    start_rotation=orientation_at(start),
                    end_rotation=rotation_of(occurrence.activity.attitude, turned),
                    early=bool(start < previous.start) or bool(end > occurrence.start),
                    into=index,
                )
            )
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
    When a turn into an attitude starts and ends, and the angle it turns through.

    The turn ends a settling time before `end`, in the target attitude as it is
    then. Its time depends on the angle, and the angle on the orientation the
    body has when the turn starts. A few rounds of guess and correct find the
    start when that orientation holds still. When it does not, because the turn
    must start partway through an earlier slew, the start is found by bisection.
    An earlier start always leaves more time than the turn needs there, so the
    bisection cannot fail.

    A turn that cannot fit starts with the run, and ends late. Otherwise it ends
    as planned.

    Parameters
    ----------
    target : str
        The attitude turned into
    end : Time
        When the activity that needs the attitude starts
    slew : Slew
        The rate, acceleration and settling time
    run_start : Time
        The start of the run
    orientation_at : callable
        The body's orientation at a time, with the slews planned so far
    rotation_of : callable
        The orientation an attitude gives at a time

    Returns
    -------
    start, turned : Time
        When the turn starts and ends, on the 1 ms grid
    angle : Quantity
        The angle turned through, in degrees
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


def _slew_rotations(
    window: SlewWindow, slew: Slew, times: TimeArray, targets: np.ndarray
) -> np.ndarray:
    """
    The orientation during a slew, at times inside it.

    During the turn, the body is partway from its starting orientation to the
    target attitude as it is at each time. The profile sets how far. While it
    settles, it holds the target attitude.

    Parameters
    ----------
    window : SlewWindow
        The slew
    slew : Slew
        The rate, acceleration and settling time
    times : Time
        Times inside the slew, one or an array
    targets : ndarray
        The target attitude's orientation at those times, shape (n, 3, 3)

    Returns
    -------
    rotations : ndarray
        Shape (n, 3, 3)
    """
    elapsed = Q_(np.atleast_1d((times - window.start).to_value(u.s)), "s")
    fractions = slew.turned(window.angle, elapsed)
    return turn_between(
        window.start_rotation, targets, fractions, reference=window.end_rotation
    )


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
        Matrices that turn body vectors into GCRS, shape (n, 3, 3), one for each
        time of the grid. Column i is body axis i, seen in GCRS.
    """
    attitude = labels_at(_attitude_row(run.occurrences), run.times)
    # the run is open at its end, so the last time takes the last activity's attitude
    attitude[-1] = run.occurrences[-1].activity.attitude

    def state_at(rows: np.ndarray) -> tuple[SkyCoord, CartesianRepresentation]:
        sun = cast(CartesianRepresentation, run.sun[rows])
        return cast(SkyCoord, run.state[rows]), sun

    rotations = np.full((len(run.times), 3, 3), np.nan)
    for name in set(attitude):
        rows = attitude == name
        rotations[rows] = attitude_rotations(run.scenario, name, *state_at(rows))
    slew = run.scenario.slew
    if slew is not None:
        # in time order, so a slew that starts partway through another wins
        for window in run.slews:
            rows = (run.times >= window.start) & (run.times < window.end)
            if rows.any():
                targets = attitude_rotations(
                    run.scenario, window.target, *state_at(rows)
                )
                rotations[rows] = _slew_rotations(
                    window, slew, run.times[rows], targets
                )
    return rotations
