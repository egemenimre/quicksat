# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Running a scenario: the orbit, the shadow, the targets' passes and the chain of
activities, in one `ScenarioRun`.

The orbits and their checks are in `sources`, the events and the chain in `events`, and
the tables in `tables`. A run of the list once, as in the Activity Designer, leaves the
time after its last activity `unplanned`. `docs/scenario/scenario_ref.ipynb`, under
"What a run gives", explains the results.

"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import cast

import numpy as np
import pandas as pd
import portion as P
from astropy.coordinates import CartesianRepresentation, SkyCoord
from astropy.units import Quantity

from quicksat import Q_, u
from quicksat.orbit.geometry import (
    beta_angle,
    elevations,
    geodetic,
    light_fraction,
    line_of_sight_clear,
    shadow_cones,
    shadow_intervals,
    sun_positions,
    sun_zenith_cosine,
)
from quicksat.orbit.trajectory import Trajectory
from quicksat.scenario.articulation import articulation_angles
from quicksat.scenario.attitude import SlewWindow, body_rotations, plan_slews
from quicksat.scenario.config import OrbitCount, Scenario
from quicksat.scenario.events import (
    STATUS_OK,
    Occurrence,
    find_events,
    resolve_activities,
)
from quicksat.scenario.grid import RunGrid
from quicksat.scenario.names import UNPLANNED
from quicksat.scenario.rates import RateExcess, rate_excesses
from quicksat.scenario.sources import (
    OrbitSource,
    orbit_warnings,
    scenario_orbit,
    target_orbits,
)
from quicksat.scenario.tables import (
    activity_summary,
    activity_table,
    gantt_rows,
    pass_table,
)
from quicksat.utils.intervals import (
    TimeArray,
    duration,
    intervals_where,
    round_time,
)


def run_length(scenario: Scenario, orbit: OrbitSource) -> Quantity:
    """
    The run's length: a time as given, or a number of orbits times the orbit's period.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    orbit : Tle or Trajectory
        The scenario's orbit

    Returns
    -------
    length : Quantity
        In s

    Raises
    ------
    ValueError
        If the step is not shorter than the run, or a trajectory is too short to measure
        an orbit
    """
    duration = scenario.duration
    if isinstance(duration, OrbitCount):
        if isinstance(orbit, Trajectory) and not orbit.period_measured:
            raise ValueError(
                "the trajectory covers less than one orbit, so it has no measured "
                "period. Give the duration as a time, such as '5 h'."
            )
        length = Q_(duration.count * orbit.period.to(u.s).value, "s")
    else:
        length = duration.to(u.s)
    if scenario.step >= length:
        raise ValueError(
            f"step must be shorter than the run, got '{scenario.step}' and "
            f"'{duration}', which is {length.to(u.min):.2f}"
        )
    return length


@dataclass(frozen=True)
class ScenarioRun:
    """
    Everything that running a scenario produces.

    Parameters
    ----------
    scenario : Scenario
        The scenario run
    orbit : Tle or Trajectory
        The element set or the trajectory
    interval : portion.Interval
        The run, closed-open
    times : Time
        The grid, end included, on the 1 ms grid
    state : SkyCoord
        The satellite's position and velocity on the grid, in GCRS
    sun : CartesianRepresentation
        The sun's position from the Earth's centre on the grid, in GCRS, in km
    latitude, longitude : Quantity
        The ground track's geodetic latitude and longitude, from -180 to 180 degrees
    beta : Quantity
        The beta angle on the grid
    eclipses, sunlit : portion.Interval
        The eclipses and the sunlit time, which together fill the run
    umbra, penumbra : portion.Interval
        The eclipses' two parts
    light : ndarray
        The share of the sun's disk seen on the grid, from 0 to 1
    illumination, attitude : portion.IntervalDict
        Two rows of the Gantt chart
    mode : dict of str to portion.IntervalDict
        The payload's and the platform's mode rows
    occurrences : list of Occurrence
        Every activity as it happens
    slews : list of SlewWindow
        Every slew, in time order
    grid : RunGrid
        The splines between the grid's steps, and the Earth's orientation
    activity_table : pd.DataFrame
        The occurrences, from `activity_table`
    sat_orbits : dict of str to Tle or Trajectory
        The satellite targets' orbits, by name
    sat_states : dict of str to SkyCoord
        The satellite targets' positions on the grid, by name
    in_view : dict of str to portion.Interval
        When each target is in view, by name
    orbit_warnings : list of str
        The warnings on the orbits
    repeat : bool
        Whether the list repeats until the run ends
    """

    scenario: Scenario
    orbit: OrbitSource
    interval: P.Interval
    times: TimeArray
    state: SkyCoord
    sun: CartesianRepresentation
    latitude: Quantity
    longitude: Quantity
    beta: Quantity  # noqa: V107
    eclipses: P.Interval
    sunlit: P.Interval
    umbra: P.Interval
    penumbra: P.Interval
    light: np.ndarray
    illumination: P.IntervalDict
    attitude: P.IntervalDict
    mode: dict[str, P.IntervalDict]
    occurrences: list[Occurrence]
    slews: list[SlewWindow]
    grid: RunGrid
    activity_table: pd.DataFrame
    sat_orbits: dict[str, OrbitSource] = field(default_factory=dict)
    sat_states: dict[str, SkyCoord] = field(default_factory=dict)
    in_view: dict[str, P.Interval] = field(default_factory=dict)
    orbit_warnings: list[str] = field(default_factory=list)
    repeat: bool = True

    @property
    def unplanned(self) -> P.Interval:
        """
        The time after the last activity, which no activity plans, empty unless the list
        ran once.
        """
        return self.attitude.find(UNPLANNED)

    @property
    def pass_length(self) -> Quantity | None:
        """
        How long one pass of the list takes, in s, as the Activity Designer shows it, or
        None when it does not end in the run.
        """
        count = len(self.scenario.activities)
        if count == 0:
            return Q_(0.0, "s")
        last = next(
            (o for o in self.occurrences if o.repeat == 1 and o.number == count), None
        )
        if last is None or last.cut_at_end or last.event_never_came:
            return None
        # an activity with a negative duration ends where it starts
        end = max(last.start, last.end)
        return (end - self.interval.lower).to(u.s)

    def check_planned(self, what: str) -> None:
        """
        Refuse to work out something that needs the activities to fill the run.

        Parameters
        ----------
        what : str
            What would be worked out, for the message

        Raises
        ------
        ValueError
            If part of the run is `unplanned`
        """
        if self.unplanned.empty:
            return
        start = cast(TimeArray, self.unplanned.lower)
        raise ValueError(
            f"Cannot work out {what}: no activity plans the run from "
            f"{start.utc.isot} to its end. Run the list with repeats, and with at "
            "least one activity."
        )

    @cached_property
    def articulations(self) -> dict[str, Quantity]:
        """
        Each articulation's angles on the grid, in degrees, by name, worked out on first
        use.
        """
        return articulation_angles(self)

    @cached_property
    def rate_excesses(self) -> list[RateExcess]:
        """
        The occurrences whose attitude turns faster than the slews may, in time order,
        worked out on first use.
        """
        return rate_excesses(self)

    @property
    def warnings(self) -> list[str]:
        """
        The warnings for the reader: the orbits', then each occurrence past the slew
        capacity.
        """
        return self.orbit_warnings + [excess.text for excess in self.rate_excesses]

    @cached_property
    def passes(self) -> pd.DataFrame:
        """Every target's passes, one row each, from `pass_table`."""
        return pass_table(self)

    @cached_property
    def sun_body(self) -> np.ndarray:
        """
        The unit direction to the sun in body axes on the grid, worked out on first use.
        A planned run only.
        """
        self.check_planned("the direction to the sun in body axes")
        cartesian = self.state.cartesian
        assert isinstance(cartesian, CartesianRepresentation)
        to_sun = self.sun.xyz.to_value(u.km).T - cartesian.xyz.to_value(u.km).T
        to_sun /= np.linalg.norm(to_sun, axis=1, keepdims=True)
        return self._in_body(to_sun)

    @cached_property
    def nadir_body(self) -> np.ndarray:
        """
        The unit direction to the Earth's centre in body axes on the grid, worked out on
        first use. A planned run only.
        """
        self.check_planned("the direction to nadir in body axes")
        cartesian = self.state.cartesian
        assert isinstance(cartesian, CartesianRepresentation)
        position = cartesian.xyz.to_value(u.km).T
        return self._in_body(
            -position / np.linalg.norm(position, axis=1, keepdims=True)
        )

    @cached_property
    def sun_zenith_cosine(self) -> np.ndarray:
        """
        The cosine of the sun's zenith angle below the satellite on the grid, on a
        spherical Earth.
        """
        return sun_zenith_cosine(self.state, self.sun)

    def _in_body(self, vectors: np.ndarray) -> np.ndarray:
        """GCRS vectors on the grid, shape (n, 3), turned into body axes."""
        # the rotations turn body vectors into GCRS, so their transposes turn back
        return np.einsum("nji,nj->ni", body_rotations(self), vectors)

    @property
    def activity_summary(self) -> str:
        """One line that sums up the occurrences."""
        return activity_summary(self.occurrences)

    @property
    def report(self) -> str:
        """
        The run's results as text, as the command prints them: the summary, the
        problems, the passes and the warnings. A planned run only.
        """
        self.check_planned("the report")
        table = self.activity_table
        problems = table[table["status"] != STATUS_OK]
        lines = [self.activity_summary]
        if not problems.empty:
            columns = ["repeat", "activity", "title", "start [UTC]", "status"]
            lines.append(problems.loc[:, columns].to_string(index=False))
        for name, seen in self.in_view.items():
            count = len(seen) if not seen.empty else 0
            minutes = duration(seen).to_value(u.min)
            lines.append(
                f"Target {name}: {count} pass{'' if count == 1 else 'es'}, "
                f"{minutes:.1f} min in view."
            )
        return "\n".join(lines + self.warnings)


def _time_above(
    times: TimeArray,
    latitude: Quantity,
    positions_at: Callable[[TimeArray], SkyCoord],
    earth_at: Callable[[TimeArray], np.ndarray],
) -> Callable[[Quantity], P.Interval]:
    """The latitude finder that `find_events` takes, over the run's grid."""

    def time_above(limit: Quantity) -> P.Interval:
        def above_at(at: TimeArray) -> np.ndarray:
            return np.asarray(geodetic(positions_at(at), earth_at)[0] >= limit)

        return intervals_where(times, np.asarray(latitude >= limit), above_at)

    return time_above


def target_visibility(
    scenario: Scenario,
    times: TimeArray,
    state: SkyCoord,
    sat_states: dict[str, SkyCoord],
    grid: RunGrid,
) -> dict[str, P.Interval]:
    """
    When each target is in view, with the edges found to 1 ms between the steps.

    A ground target sees the satellite at or above its minimum elevation, and a
    satellite target keeps the line of sight above its minimum clearance.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    times : Time
        The run's grid
    state : SkyCoord
        The satellite's state on the grid
    sat_states : dict of str to SkyCoord
        The satellite targets' positions on the grid, by name
    grid : RunGrid
        The splines between the grid's steps

    Returns
    -------
    in_view : dict of str to portion.Interval
        The time each target is in view, by name
    """
    found = {}

    def positions_at(at: TimeArray) -> SkyCoord:
        return grid.satellite.states(at, with_velocity=False)

    for name, ground in scenario.gnd_targets.items():
        place = (ground.latitude, ground.longitude, ground.altitude)
        lowest = ground.min_elevation.to_value(u.deg)

        def visible_at(at: TimeArray, place=place, lowest=lowest) -> np.ndarray:
            seen = elevations(positions_at(at), *place, earth_at=grid.earth)
            return seen >= lowest

        flags = elevations(state, *place, earth_at=grid.earth) >= lowest
        found[name] = intervals_where(times, flags, visible_at)
    for name, target in scenario.sat_targets.items():
        orbit, clearance = grid.targets[name], target.min_clearance

        def clear_at(at: TimeArray, orbit=orbit, clearance=clearance) -> np.ndarray:
            other = orbit.states(at, with_velocity=False)
            return line_of_sight_clear(positions_at(at), other, clearance, grid.earth)

        flags = line_of_sight_clear(state, sat_states[name], clearance, grid.earth)
        found[name] = intervals_where(times, flags, clear_at)
    return found


def run_scenario(scenario: Scenario, repeat: bool = True) -> ScenarioRun:  # noqa: V103
    """
    Run a scenario.

    The orbits are evaluated on the grid, and the shadow, the latitude crossings and the
    targets' passes are found between the steps through splines, `RunGrid`. The
    activities are then chained over the run and checked.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    repeat : bool, optional
        Whether to repeat the list until the run ends, or run it once

    Returns
    -------
    result : ScenarioRun
        The run

    Raises
    ------
    ValueError
        If no activity in the list takes any time, a satellite target's orbit fails, or
        the run leaves a trajectory
    """
    orbit = scenario_orbit(scenario)
    sat_orbits = target_orbits(scenario)
    start = round_time(scenario.start)

    duration_s = run_length(scenario, orbit).to(u.s).value
    step_s = scenario.step.to(u.s).value
    steps = int(np.ceil(duration_s / step_s))
    offsets = np.unique(np.minimum(np.arange(steps + 1) * step_s, duration_s))
    times = round_time(start + Q_(offsets, "s"))
    interval = P.closedopen(times[0], times[-1])
    warnings = orbit_warnings(scenario, orbit, sat_orbits, times[0], times[-1])

    state = orbit.states(times)
    sun = sun_positions(times)
    sat_states = {}
    for name, source in sat_orbits.items():
        try:
            sat_states[name] = source.states(times, with_velocity=False)
        except ValueError as error:
            raise ValueError(f"satellite target '{name}': {error}") from error
    grid = RunGrid(times, orbit, state, sun, sat_orbits, sat_states)

    def positions_at(at: TimeArray) -> SkyCoord:
        return grid.satellite.states(at, with_velocity=False)

    umbra, eclipses = shadow_intervals(
        times, shadow_cones(state, sun), positions_at, grid.sun
    )
    illumination = {
        "sunlit": interval - eclipses,
        "penumbra": eclipses - umbra,
        "umbra": umbra,
        "eclipse": eclipses,
    }
    latitude, longitude = geodetic(state, grid.earth)
    in_view = target_visibility(scenario, times, state, sat_states, grid)
    events = find_events(
        scenario.activities,
        interval,
        illumination,
        _time_above(times, latitude, positions_at, grid.earth),
        in_view.__getitem__,
    )
    occurrences = resolve_activities(
        scenario.activities, interval, events, illumination, repeat
    )
    slews = []
    if scenario.slew is not None:
        slews = plan_slews(
            occurrences,
            scenario.slew,
            scenario,
            interval,
            grid.satellite.states,
            grid.sun,
            grid.targets,
            grid.earth,
        )
        for window in slews:
            occurrences[window.into] = replace(
                occurrences[window.into],
                slew=window.duration,
                slew_starts_early=window.early,
            )
    illumination_row, attitude, mode = gantt_rows(illumination, occurrences, slews)

    return ScenarioRun(
        scenario=scenario,
        orbit=orbit,
        interval=interval,
        times=times,
        state=state,
        sun=sun,
        latitude=latitude,
        longitude=longitude,
        beta=beta_angle(state, sun),
        eclipses=eclipses,
        sunlit=illumination["sunlit"],
        umbra=umbra,
        penumbra=illumination["penumbra"],
        light=light_fraction(state, sun),
        illumination=illumination_row,
        attitude=attitude,
        mode=mode,
        occurrences=occurrences,
        slews=slews,
        grid=grid,
        activity_table=activity_table(occurrences),
        sat_orbits=sat_orbits,
        sat_states=sat_states,
        in_view=in_view,
        orbit_warnings=warnings,
        repeat=repeat,
    )
