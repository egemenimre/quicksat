# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Running a scenario: the orbit, the eclipses and the repeated activities.

`run_scenario` evaluates the orbit on the time grid and finds the umbra and the
penumbra, and the latitude crossings that the triggers name. It finds when each
target is in view: a ground target above its minimum elevation, and a satellite
target with the line between the two above its minimum clearance. It repeats the
list of activities until the duration ends and checks each constraint. All the
results come back in one `ScenarioRun`.

The run's parts have modules of their own: the orbits and their checks in
`sources`, the events and the chain of activities in `events`, and the tables in
`tables`.

The Activity Designer can run the list once, with no repeats, or run an empty
list. The time after the last activity is then unplanned. The attitude and both
mode rows give it as `unplanned`, and the body has no orientation then. Whatever
needs the whole run planned refuses such a run.

Each orbit is checked against the run before it is used. An element set more
than 7 days from either end of the run gets a warning, and so does a trajectory
whose ends come close to the run's. A trajectory that does not cover the run
stops it. The warnings come back in `ScenarioRun.warnings`, as well as through
Python's warnings.

Every time interval is closed at its start and open at its end. Every bound goes
through `round_time`. So the pieces of a run fit together with no gaps and no
overlaps.

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
    The length of the run, as a time.

    A duration given as a time is used as it is. A number of orbits is multiplied
    by the orbit's period: the nodal period of an element set, or the period
    measured from a trajectory.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    orbit : Tle or Trajectory
        Where the scenario's states come from

    Returns
    -------
    length : Quantity
        The length of the run, in seconds

    Raises
    ------
    ValueError
        If the step is not shorter than the run, or if the duration is in orbits
        and the trajectory is too short to measure one
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
        The scenario that was run
    orbit : Tle or Trajectory
        Where the states come from: the element set, or the trajectory
    interval : portion.Interval
        The run, closed at its start and open at its end
    times : Time
        The time grid, from the start to the end of the run, in steps. The end is
        included, and the last step is shorter if the step does not divide the
        duration. Every time is on the 1 ms grid.
    state : SkyCoord
        The satellite's position and velocity on the grid, in GCRS
    sun : CartesianRepresentation
        The position of the sun relative to the centre of the Earth on the grid,
        in GCRS, in km
    latitude, longitude : Quantity
        Geodetic latitude and longitude of the ground track on the grid, with the
        longitude from -180 to 180 degrees
    beta : Quantity
        The beta angle on the grid
    eclipses, sunlit : portion.Interval
        The eclipse and sunlit intervals, which together fill the run
    umbra, penumbra : portion.Interval
        The two parts of the eclipses: where the Earth hides the whole sun, and
        where it hides part of it
    light : ndarray
        The fraction of the sun's disk seen at each time of the grid, from 0 to 1
    illumination, attitude : portion.IntervalDict
        Two rows of the Gantt chart
    mode : dict of str to portion.IntervalDict
        The other two: the payload's and the platform's modes, by the group's
        name, `payload` or `platform`
    occurrences : list of Occurrence
        Every activity as it happens in the run. In a run of the list once, or
        of an empty list, they stop before the end: see `unplanned`.
    slews : list of SlewWindow
        Every slew between attitudes, in time order. Empty when the scenario has
        no slews.
    grid : RunGrid
        The orbits, the sun and the Earth's orientation between the grid's
        steps, and the Earth's orientation on the grid
    activity_table : pd.DataFrame
        The occurrences as a table, from `activity_table`
    sat_orbits : dict of str to Tle or Trajectory
        Where each satellite target's states come from, by its name
    sat_states : dict of str to SkyCoord
        Each satellite target's positions on the grid, in GCRS, by its name
    in_view : dict of str to portion.Interval
        When each target is in view, ground and satellite, by its name
    orbit_warnings : list of str
        The warnings on the orbits, from `orbit_warnings`: an element set far
        from the run, or a trajectory whose ends come close to it
    repeat : bool
        Whether the list of activities repeats until the run ends, as it does
        but in the Activity Designer
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
        The time after the last activity, which no activity plans.

        Returns
        -------
        unplanned : portion.Interval
            Empty, unless the list ran once and ended before the run, or was
            empty
        """
        return self.attitude.find(UNPLANNED)

    @property
    def pass_length(self) -> Quantity | None:
        """
        How long one pass of the list of activities takes, from the start of the
        run, as the Activity Designer shows it.

        Returns
        -------
        length : Quantity or None
            In seconds. Zero for an empty list. None when the pass does not end
            in the run: the run ends first, or an event that never comes stops
            the list.
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
            What would be worked out, such as "the report", for the message

        Raises
        ------
        ValueError
            If part of the run is unplanned: see `unplanned`
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
        The angle of each articulation of the 3D model, from `articulation_angles`.

        Worked out on first use, because it needs the body's orientation at each
        step.

        Returns
        -------
        angles : dict of str to Quantity
            For each articulation, by its name, its angles in degrees on the grid.
            Empty without articulations.
        """
        return articulation_angles(self)

    @cached_property
    def rate_excesses(self) -> list[RateExcess]:
        """
        The occurrences whose attitude turns faster than the slews may.

        Worked out on first use, from `rate_excesses`. Empty without a `slew`
        block.

        Returns
        -------
        excesses : list of RateExcess
            In time order
        """
        return rate_excesses(self)

    @property
    def warnings(self) -> list[str]:
        """
        Warnings for the reader, as text: the orbits' warnings, then each
        occurrence past the slew capacity.

        Returns
        -------
        warnings : list of str
            One sentence or two for each, the occurrences in time order. Empty
            when there are none.
        """
        return self.orbit_warnings + [excess.text for excess in self.rate_excesses]

    @cached_property
    def passes(self) -> pd.DataFrame:
        """
        Every target's passes, from `pass_table`.

        Returns
        -------
        table : pd.DataFrame
            One row for each time a target is in view
        """
        return pass_table(self)

    @cached_property
    def sun_body(self) -> np.ndarray:
        """
        The direction from the satellite to the sun in body axes, on the grid.

        Worked out on first use, from `body_rotations`, so that it follows the
        body through its slews.

        Returns
        -------
        suns : ndarray
            Unit vectors, shape (n, 3), one for each time of the grid

        Raises
        ------
        ValueError
            If part of the run is unplanned, so that the body has no orientation
            then
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
        The direction from the satellite to the centre of the Earth in body axes,
        on the grid.

        Worked out on first use, from `body_rotations`, as `sun_body` is. It is
        the `nadir` of the attitudes.

        Returns
        -------
        nadirs : ndarray
            Unit vectors, shape (n, 3), one for each time of the grid

        Raises
        ------
        ValueError
            If part of the run is unplanned, so that the body has no orientation
            then
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
        The cosine of the sun's zenith angle at the point below the satellite, on
        the grid.

        It is worked out from the geocentric directions of the satellite and the
        sun, on a spherical Earth, by `sun_zenith_cosine`. It is 1 at the
        subsolar point, 0 at the terminator, and negative over the night side.

        Returns
        -------
        cosines : ndarray
            One for each time of the grid, from -1 to 1
        """
        return sun_zenith_cosine(self.state, self.sun)

    def _in_body(self, vectors: np.ndarray) -> np.ndarray:
        """GCRS vectors on the grid, shape (n, 3), turned into body axes."""
        # the rotations turn body vectors into GCRS, so their transposes turn back
        return np.einsum("nji,nj->ni", body_rotations(self), vectors)

    @property
    def activity_summary(self) -> str:
        """
        One line that sums up the occurrences, from `activity_summary`.

        Returns
        -------
        summary : str
        """
        return activity_summary(self.occurrences)

    @property
    def report(self) -> str:
        """
        The run's results as text, as the command line prints them.

        Returns
        -------
        report : str
            The summary line, a table of the occurrences whose status is not
            `ok`, if any, a line for each target with its passes and its time in
            view, and the warnings, one line each

        Raises
        ------
        ValueError
            If part of the run is unplanned
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
    """
    The latitude finder that `find_events` takes, over a run's grid.

    Parameters
    ----------
    times : Time
        The run's grid
    latitude : Quantity
        The geodetic latitude on the grid
    positions_at : callable
        Gives the satellite's positions for any `Time` array
    earth_at : callable
        Gives the Earth's orientation for any `Time` array, as `earth_rotations`
        does

    Returns
    -------
    time_above : callable
        Gives the time at or above a geodetic latitude
    """

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
    When each target is in view, ground and satellite, over a run's grid.

    A ground target is in view while it sees the satellite at or above its
    minimum elevation. A satellite target is in view while the line between the
    two keeps its minimum clearance above the WGS84 ellipsoid. The edges are found
    between the grid steps, to 1 ms.

    Parameters
    ----------
    scenario : Scenario
        The scenario, for its targets
    times : Time
        The run's grid
    state : SkyCoord
        The satellite's state on the grid
    sat_states : dict of str to SkyCoord
        The satellite targets' positions on the grid, by name
    grid : RunGrid
        The orbits and the Earth's orientation between the grid's steps

    Returns
    -------
    in_view : dict of str to portion.Interval
        For each target, by its name, the time it is in view
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

    The orbit comes from the TLE file, from a TLE built for the sun-synchronous
    orbit, or from the trajectory file. It is evaluated on the time grid, with
    SGP4 or by interpolation, and so is each satellite target's orbit. The edges
    of the umbra and the penumbra are then located between the grid steps, and
    so are the latitude crossings that the triggers name, and the edges of each
    target's time in view. Between the steps, the orbits, the sun and the
    Earth's orientation come from splines through the grid: see `RunGrid`. The
    activities are then repeated over the run and checked against the eclipses.
    Each orbit is checked against the run first: see `orbit_warnings`.

    Parameters
    ----------
    scenario : Scenario
        The scenario, from `Scenario.from_yaml_file`
    repeat : bool, optional
        Whether to repeat the list of activities until the run ends, as by
        default, or run it once, as the Activity Designer does at first. The
        time after a single pass is unplanned.

    Returns
    -------
    result : ScenarioRun
        The orbit, the eclipses, the activities and the checks

    Raises
    ------
    ValueError
        If no activity in the list ends after it starts, if a satellite target's
        file does not give its orbit, if the run does not lie inside a
        trajectory, or if SGP4 fails for a satellite target. A message about a
        satellite target names it.
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
