# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Where a run's states come from: the scenario's orbit, and its satellite targets'
orbits.

Each is an element set for SGP4 or a trajectory. `orbit_warnings` checks each
against the run: an element set's epoch far from the run, or a trajectory whose
ends come close to the run's.

"""

from pathlib import Path

from quicksat.orbit.omm import read_omm_file, read_omm_sets
from quicksat.orbit.sso import sso_tle
from quicksat.orbit.tle import (
    Tle,
    pick_element_set,
    read_tle_file,
    read_tle_sets,
    warn_if_far_from_epoch,
)
from quicksat.orbit.trajectory import Trajectory
from quicksat.orbit.trajectory_files import read_trajectory_file
from quicksat.scenario.config import Scenario
from quicksat.utils.intervals import (
    TimeArray,
    round_time,
)

OrbitSource = Tle | Trajectory
"""Where a run's states come from: an element set for SGP4, or a trajectory.
Each gives a `name`, a `period` for a duration in orbits, and `states(times)` in
GCRS."""


def scenario_orbit(scenario: Scenario) -> OrbitSource:
    """
    Where the scenario's states come from.

    An element set is read from the TLE file or the OMM file, or built for the
    sun-synchronous orbit, with its epoch at the start of the run. A trajectory
    is read from the trajectory file.

    Parameters
    ----------
    scenario : Scenario
        The scenario

    Returns
    -------
    orbit : Tle or Trajectory
        The element set or the trajectory
    """
    orbit = scenario.orbit
    if orbit.sso is not None:
        sso = orbit.sso
        name = f"SSO {sso.altitude:g}, {sso.node_label}"
        return sso_tle(
            round_time(scenario.start), sso.altitude, sso.ascending_node_time, name=name
        )
    if orbit.trajectory_file is not None:
        return read_trajectory_file(orbit.trajectory_file)
    if orbit.omm_file is not None:
        return read_omm_file(orbit.omm_file)
    assert orbit.tle_file is not None  # the orbit has exactly one of the four
    return read_tle_file(orbit.tle_file)


def target_orbits(scenario: Scenario) -> dict[str, OrbitSource]:
    """
    Where each satellite target's states come from, read from its file.

    A TLE or OMM file gives the element set that the target's `object` names.
    Without `object`, a file of one element set gives that one, and a file of
    several gives the one named as the target. A file that several targets share
    is read once.

    Parameters
    ----------
    scenario : Scenario
        The scenario

    Returns
    -------
    orbits : dict of str to Tle or Trajectory
        Each satellite target's element set or trajectory, by its name

    Raises
    ------
    FileNotFoundError
        If a target's file does not exist
    ValueError
        If a target's file cannot be read, or does not hold the element set asked
        for. The message names the target.
    """
    read: dict[Path, list[Tle]] = {}
    orbits: dict[str, OrbitSource] = {}
    for name, target in scenario.sat_targets.items():
        try:
            if target.trajectory_file is not None:
                orbits[name] = read_trajectory_file(target.trajectory_file)
                continue
            path = target.file
            if path not in read:
                reader = read_tle_sets if target.tle_file is not None else read_omm_sets
                read[path] = reader(path)
            wanted = target.satellite
            if wanted is None and len(read[path]) > 1:
                wanted = name
            orbits[name] = pick_element_set(read[path], wanted, path)
        except (OSError, ValueError) as error:
            raise type(error)(f"satellite target '{name}': {error}") from error
    return orbits


def orbit_warnings(
    scenario: Scenario,
    orbit: OrbitSource,
    sat_orbits: dict[str, OrbitSource],
    start: TimeArray,
    end: TimeArray,
) -> list[str]:
    """
    Check each orbit against the run: an element set's epoch, and a trajectory's
    span.

    An element set gets a warning when either end of the run is more than 7
    days from its epoch. The sun-synchronous orbit is left out: quicksat builds
    its element set, with the epoch at the start, so it defines the orbit rather
    than tracking one. A trajectory must cover the run, and gets a warning when
    the run comes close to one of its ends.

    Parameters
    ----------
    scenario : Scenario
        The scenario
    orbit : Tle or Trajectory
        Where the scenario's own states come from
    sat_orbits : dict of str to Tle or Trajectory
        The satellite targets' orbits, by name
    start, end : Time
        The start and the end of the run

    Returns
    -------
    warnings : list of str
        The text of each warning, which Python's warnings also give

    Raises
    ------
    ValueError
        If a trajectory does not cover the run, or crosses a gap in it
    """
    labels: dict[str, OrbitSource] = {}
    if isinstance(orbit, Trajectory):
        labels["the trajectory"] = orbit
    elif scenario.orbit.sso is None:
        labels["the orbit's element set"] = orbit
    for name, source in sat_orbits.items():
        if isinstance(source, Trajectory):
            labels[f"the trajectory of satellite target '{name}'"] = source
        else:
            labels[f"satellite target '{name}'"] = source
    found = []
    for label, source in labels.items():
        if isinstance(source, Trajectory):
            text = source.check_covers(start, end, label)
        else:
            text = warn_if_far_from_epoch(source, start, end, label)
        if text is not None:
            found.append(text)
    return found
