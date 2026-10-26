# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The scenario file: the orbit, the period, the attitudes and the activities.

This module reads and checks the file, and runs nothing. The orbit and the targets are
in `orbit_config`, the triggers in `triggers`, the activities in `activities`, and the
shared names in `names`. `docs/scenario/scenario_ref.ipynb`, under "The scenario file",
explains the file.

"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Annotated, Self

import numpy as np
from astropy.time import Time
from astropy.units import Quantity
from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from quicksat import Q_, u
from quicksat.orbit.attitude import slew_duration, slew_progress
from quicksat.scenario.activities import Activity
from quicksat.scenario.names import DIRECTIONS, FALLBACKS, RESERVED_NAMES, SLEW, Axis
from quicksat.scenario.orbit_config import GroundTarget, Orbit, SatelliteTarget
from quicksat.scenario.spacecraft import node_index, read_glb_json
from quicksat.utils.parser_helpers import (
    AngularAccelerationQty,
    AngularRateQty,
    Commented,
    SignedAngleQty,
    TimeQty,
    YamlFile,
    without_comments,
)

DEFAULT_STEP = Q_(10, "s")
"""The time step, when the scenario does not give one."""


def _different_axes(first: str, second: str, names: str) -> None:
    """Refuses two axes of one attitude on the same body axis, whatever their signs."""
    if first[1] == second[1]:
        raise ValueError(
            f"{names} must use different body axes, got '{first}' and '{second}'"
        )


def _read_pair(value) -> tuple[str, str]:
    """
    An `[axis, direction]` pair, stripped, refusing anything but a list of two strings.
    """
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(item, str) for item in value)
    ):
        raise ValueError(
            f"expected a pair [axis, direction], such as [+z, nadir], got {value!r}"
        )
    return value[0].strip(), value[1].strip()


AxisPair = Annotated[tuple[Axis, str], BeforeValidator(_read_pair)]
"""A body axis and the direction it goes with, written `[+z, nadir]`."""

_OFFSET_TURN = re.compile(r"\s*([xyz])\s+(.+?)\s*")


def _read_offsets(value) -> list[tuple[str, Quantity]]:
    """
    An attitude's offset turns as an axis letter and an angle in degrees each, in order.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(
            f"offset must be a list of turns, such as [x 30 deg], got {value!r}"
        )
    turns = []
    for item in value:
        match = _OFFSET_TURN.fullmatch(item) if isinstance(item, str) else None
        if match is None:
            raise ValueError(
                f"an offset turn is a body axis, x, y or z, and an angle, such as "
                f"'x 30 deg', got {item!r}"
            )
        axis, text = match.groups()
        try:
            angle = Q_(text)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"the offset turn '{item}' has no angle") from exc
        if angle.unit is None or not angle.unit.is_equivalent(u.deg):
            raise ValueError(
                f"the offset turn '{item}' needs an angle with its unit, such as 30 deg"
            )
        turns.append((axis, angle.to(u.deg)))
    return turns


class Attitude(Commented):
    """
    An attitude: one body axis fixed on a direction, and a second turned as close as it
    can to another.

    A direction is one of `DIRECTIONS`, or a target's name.

    Parameters
    ----------
    point : tuple of str
        The body axis and its direction, `[+z, nadir]`
    constrain : tuple of str
        A second body axis and its direction, `[-y, orbit normal]`
    fallback : str, optional
        The direction that replaces the constraint's where it is parallel to the pointed
        one. By default, the first of `FALLBACKS` not used
    offset : list, optional
        Turns about the body's own axes, in order, after the orientation, `[x 30 deg]`
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    point: AxisPair
    constrain: AxisPair
    fallback: str | None = None
    offset: Annotated[list[tuple[str, Quantity]], BeforeValidator(_read_offsets)] = (
        Field(default_factory=list)
    )

    @model_validator(mode="after")
    def _check(self):
        """Checks the two axes, the two directions, and that a fallback is a third."""
        _different_axes(self.point[0], self.constrain[0], "point and constrain")
        if self.point[1] == self.constrain[1]:
            raise ValueError(
                f"point and constrain must use different directions, got "
                f"'{self.point[1]}' for both"
            )
        if self.fallback is not None and self.fallback in (
            self.point[1],
            self.constrain[1],
        ):
            raise ValueError(
                f"fallback must be a direction that point and constrain do not "
                f"use, got '{self.fallback}'"
            )
        return self

    @property
    def fallback_direction(self) -> str:
        """
        The direction that replaces the constraint's where it is parallel: `fallback`,
        or the first of `FALLBACKS` not used.
        """
        if self.fallback is not None:
            return self.fallback
        used = {self.point[1], self.constrain[1]}
        return next(direction for direction in FALLBACKS if direction not in used)

    @property
    def directions(self) -> list[str]:
        """
        Every direction the attitude uses: the pointed one, the constraint's, and the
        fallback.
        """
        return [self.point[1], self.constrain[1], self.fallback_direction]


_ORBIT_COUNT = re.compile(r"(\d+(?:\.\d*)?|\.\d+)\s*orbits?", re.IGNORECASE)
"""A duration written as a number of orbits, such as `3 orbits` or `1 orbit`."""


@dataclass(frozen=True)
class OrbitCount:
    """
    A duration as a number of orbits, each the element set's nodal period, turned into a
    time by the run.

    Parameters
    ----------
    count : float
        The number of orbits, positive
    """

    count: float

    def __str__(self) -> str:
        """The count as written in a scenario file, such as `3 orbits`."""
        return f"{self.count:g} orbit{'' if self.count == 1 else 's'}"


def _parse_duration(value) -> Quantity | OrbitCount:
    """
    The run's duration, as a positive time or a number of orbits, such as `3 orbits`.
    """
    example = "such as 5 h, or a number of orbits, such as 3 orbits"
    if isinstance(value, str):
        match = _ORBIT_COUNT.fullmatch(value.strip())
        if match:
            count = float(match.group(1))
            if count <= 0:
                raise ValueError(f"duration must be positive, got '{value}'")
            return OrbitCount(count)
    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise ValueError(f"duration must be a time with a unit, {example}. Got {value}")
    if isinstance(value, Quantity):
        time = value
    else:
        try:
            time = Q_(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(
                f"duration must be a time with a unit, {example}. Got '{value}'"
            ) from None
    if not u.s.is_equivalent(time.unit):
        raise ValueError(
            f"duration must be a time with a unit, {example}. Got '{time}'"
        )
    if time <= Q_(0, "s"):
        raise ValueError(f"duration must be positive, got '{time}'")
    return time


def _parse_start(value) -> Time:
    """
    The start time from an ISO time, or YAML's datetime, in UTC. A date alone is
    midnight.
    """
    if isinstance(value, Time):
        return value
    message = (
        f"start must be an ISO time in UTC, such as 2026-10-01T00:00:00, got {value!r}"
    )
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return Time(value, scale="utc")
    if isinstance(value, date):
        return Time(datetime.combine(value, time()), scale="utc")
    if isinstance(value, str):
        for time_format in ("isot", "iso"):
            try:
                return Time(value.strip(), format=time_format, scale="utc")
            except ValueError:
                continue
    raise ValueError(message)


class Slew(Commented):
    """
    How the body turns from one attitude to another: rest to rest about one axis, then
    settling.

    The same limits hold for every axis.

    Parameters
    ----------
    max_rate : Quantity, optional
        The fastest turn, such as `0.7 deg/s`
    max_acceleration : Quantity, optional
        The fastest change of rate, such as `0.08 deg/s2`
    settling_time : Quantity, optional
        The time to settle after the turn, by default 0 s
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    max_rate: AngularRateQty | None = None
    max_acceleration: AngularAccelerationQty | None = None
    settling_time: TimeQty = Q_(0, "s")

    @model_validator(mode="after")
    def _a_positive_limit(self):
        """Checks for at least one limit, each above zero."""
        limits = {"max_rate": self.max_rate, "max_acceleration": self.max_acceleration}
        given = {name: limit for name, limit in limits.items() if limit is not None}
        if not given:
            raise ValueError("a slew needs max_rate, max_acceleration, or both")
        for name, limit in given.items():
            if limit <= 0:
                raise ValueError(f"{name} must be positive, got '{limit}'")
        return self

    def _limits(self) -> tuple[float | None, float | None]:
        """The maximum rate and acceleration in rad/s and rad/s2, or None for either."""
        rate = None if self.max_rate is None else self.max_rate.to(u.rad / u.s).value
        acceleration = (
            None
            if self.max_acceleration is None
            else self.max_acceleration.to(u.rad / u.s**2).value
        )
        return rate, acceleration

    def turn_time(self, angle: Quantity) -> Quantity:
        """
        How long the turn through an angle takes, settling excluded.

        Parameters
        ----------
        angle : Quantity
            The angle to turn through

        Returns
        -------
        time : Quantity
            In s
        """
        seconds = slew_duration(np.asarray(angle.to(u.rad).value), *self._limits())
        return Q_(float(seconds), "s")

    def turned(self, angle: Quantity, elapsed: Quantity) -> np.ndarray:
        """
        How far through the turn the body is, from 0 to 1.

        Parameters
        ----------
        angle : Quantity
            The turn's whole angle
        elapsed : Quantity
            The time since the turn started

        Returns
        -------
        fraction : ndarray
            0 at the start, 1 once the turn is over
        """
        return slew_progress(
            float(angle.to(u.rad).value), elapsed.to(u.s).value, *self._limits()
        )


FULL_TURN = (Q_(-180, "deg"), Q_(180, "deg"))
"""The range of an articulation that can turn all the way round."""


class Articulation(Commented):
    """
    A part of the 3D model that turns about one body axis, such as a solar wing that
    follows the sun.

    The part turns until its pointing axis comes as close to its direction as it can. In
    a platform mode that `park` names, it holds that angle instead.
    `docs/scenario/scenario_ref.ipynb`, under "Articulations", explains them.

    Parameters
    ----------
    part : str
        The GLB node that turns, about its own origin, with its children
    axis : str
        The drive axis, in body axes, such as `+y`
    point : tuple of str
        The part's axis and its direction, `[-z, sun]`, on another body axis than `axis`
    range : tuple of Quantity, optional
        The lowest and highest angle, by default all the way round
    park : dict of str to Quantity, optional
        A fixed angle for each platform mode named, in the range
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    part: str
    axis: Axis
    point: AxisPair
    range: tuple[SignedAngleQty, SignedAngleQty] = FULL_TURN
    park: dict[str, SignedAngleQty] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self):
        """Checks the axes, the range, and that each park angle is in it."""
        _different_axes(self.axis, self.point[0], "axis and point")
        low, high = self.range
        if not FULL_TURN[0] <= low < high <= FULL_TURN[1]:
            raise ValueError(
                f"range must rise from low to high within -180 to 180 deg, got "
                f"[{low}, {high}]"
            )
        for mode, angle in self.park.items():
            if not low <= angle <= high:
                raise ValueError(
                    f"the park angle for '{mode}', {angle}, is outside the range "
                    f"[{low}, {high}]"
                )
        return self


def _model_mapping(value):
    """Reads a `3d_model` given as a file name as the mapping with only `file`."""
    if isinstance(value, (str, Path)):
        return {"file": value}
    return value


class SpacecraftModel(Commented):
    """
    The spacecraft's 3D model, and the parts of it that turn.

    Parameters
    ----------
    file : Path
        The GLB file, in body axes and metres
    articulations : dict of str to Articulation, optional
        The parts that turn, by any names
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    file: Path
    articulations: Annotated[
        dict[str, Articulation], BeforeValidator(without_comments)
    ] = Field(default_factory=dict)


class Scenario(YamlFile):
    """
    A scenario: the orbit, the period of the run, and the activities.

    Parameters
    ----------
    orbit : Orbit
        Where the orbit comes from
    start : Time
        The run's start, in UTC
    duration : Quantity or OrbitCount
        The run's length, positive, such as `5 h` or `3 orbits`
    step : Quantity
        The grid's time step, by default 10 s
    gnd_targets : dict of str to GroundTarget, optional
        Ground points, by name
    sat_targets : dict of str to SatelliteTarget, optional
        Other satellites, by name
    attitudes : dict of str to Attitude
        The attitudes, by any names but `slew` and `unplanned`
    activities : list of Activity
        One pass of the activities, which the run repeats. The Activity Designer allows
        an empty list
    slew : Slew, optional
        How the body turns, by default at once
    spacecraft_model : SpacecraftModel, optional
        The 3D model, written `3d_model`, by default a 1 m cube
    comments : str, optional
        The user's notes, which quicksat does not read
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    orbit: Orbit
    start: Annotated[Time, BeforeValidator(_parse_start)]
    duration: Annotated[Quantity | OrbitCount, BeforeValidator(_parse_duration)]
    step: TimeQty = DEFAULT_STEP
    gnd_targets: Annotated[
        dict[str, GroundTarget], BeforeValidator(without_comments)
    ] = Field(default_factory=dict)
    sat_targets: Annotated[
        dict[str, SatelliteTarget], BeforeValidator(without_comments)
    ] = Field(default_factory=dict)
    attitudes: Annotated[dict[str, Attitude], BeforeValidator(without_comments)]
    activities: list[Activity]
    slew: Slew | None = None
    spacecraft_model: Annotated[
        SpacecraftModel | None, BeforeValidator(_model_mapping)
    ] = Field(None, alias="3d_model")

    @classmethod
    def from_yaml_file(cls, file_path: str | Path, designer: bool = False) -> Self:
        """
        Read the scenario file. Its relative paths are taken from its folder.

        Parameters
        ----------
        file_path : str or Path
            The scenario file
        designer : bool, optional
            Read it as the Activity Designer does

        Returns
        -------
        scenario : Scenario
            The scenario
        """
        return cls._from_file(file_path, designer=designer)

    @classmethod
    def from_yaml_text(
        cls,
        yaml_text: str,
        base_dir: str | Path | None = None,
        designer: bool = False,
    ) -> Self:
        """
        Read the scenario from YAML text.

        Parameters
        ----------
        yaml_text : str
            The text
        base_dir : str or Path, optional
            The folder for relative paths, by default the working directory
        designer : bool, optional
            Allow an empty list, and park modes no activity gives yet, as the Activity
            Designer does

        Returns
        -------
        scenario : Scenario
            The scenario
        """
        return cls._from_text(yaml_text, base_dir=base_dir, designer=designer)

    @field_validator("step")
    @classmethod
    def _positive(cls, value, info: ValidationInfo):
        """Checks that the step is above zero."""
        if value <= Q_(0, "s"):
            raise ValueError(f"{info.field_name} must be positive, got '{value}'")
        return value

    @field_validator("spacecraft_model")
    @classmethod
    def _read_model(
        cls, model: SpacecraftModel | None, info: ValidationInfo
    ) -> SpacecraftModel | None:
        """
        Takes a relative model path from the file's folder, and checks the model and its
        articulations' nodes.
        """
        if model is None:
            return None
        path = model.file
        base_dir = (info.context or {}).get("base_dir")
        if base_dir is not None and not path.is_absolute():
            path = Path(base_dir) / path
        if not path.is_file():
            raise ValueError(f"no such file: {path}")
        gltf = read_glb_json(path)
        problems = []
        for name, articulation in model.articulations.items():
            try:
                node_index(gltf, articulation.part)
            except ValueError as exc:
                problems.append(f"articulation '{name}': {exc}")
        if problems:
            raise ValueError("\n".join(problems))
        return model.model_copy(update={"file": path})

    @field_validator("attitudes")
    @classmethod
    def _name_attitudes(cls, attitudes: dict[str, Attitude]) -> dict[str, Attitude]:
        """Checks there is an attitude, and each name can be used."""
        if not attitudes:
            raise ValueError("attitudes must define at least one attitude")
        for name in attitudes:
            if not name.strip():
                raise ValueError("an attitude's name must not be empty")
            if name in RESERVED_NAMES:
                raise ValueError(
                    f"no attitude may be named '{name}': {RESERVED_NAMES[name]}"
                )
        return attitudes

    @field_validator("activities", mode="before")
    @classmethod
    def _read_activities(cls, value, info: ValidationInfo):
        """Reads each activity in either form, naming it by its number on an error."""
        designer = (info.context or {}).get("designer", False)
        if designer and value is None:
            value = []
        if not isinstance(value, list) or (not value and not designer):
            raise ValueError("activities must be a list of at least one activity")
        activities, problems = [], []
        for number, fields in enumerate(value, start=1):
            try:
                if isinstance(fields, dict):
                    activities.append(Activity.from_mapping(fields))
                else:
                    activities.append(Activity.from_fields(fields))
            except ValueError as exc:
                problems.append(f"activity {number}: {exc}")
        if problems:
            raise ValueError("\n".join(problems))
        return activities

    def _direction_problems(self) -> list[str]:
        """
        Each problem with the names of the targets, the directions, the attitudes and
        the triggers' targets.
        """
        targets = [*self.gnd_targets, *self.sat_targets]
        problems = [
            f"target '{name}' takes the name of a built-in direction. The built-in "
            f"directions are: {list(DIRECTIONS)}"
            for name in targets
            if name in DIRECTIONS
        ]
        problems += [
            f"target '{name}' is in both gnd_targets and sat_targets. A target's "
            "name must be its own."
            for name in self.gnd_targets
            if name in self.sat_targets
        ]
        known = [*DIRECTIONS, *dict.fromkeys(targets)]
        for name, attitude in self.attitudes.items():
            problems += [
                f"attitude '{name}': '{direction}' is not a direction. The "
                f"directions are: {known}"
                for direction in attitude.directions
                if direction not in known
            ]
        if self.spacecraft_model is not None:
            problems += [
                f"articulation '{name}': '{articulation.point[1]}' is not a "
                f"direction. The directions are: {known}"
                for name, articulation in self.spacecraft_model.articulations.items()
                if articulation.point[1] not in known
            ]
        defined = list(self.attitudes)
        problems += [
            f"activity {number}: attitude '{activity.attitude}' is not defined in "
            f"attitudes, which define: {defined}"
            for number, activity in enumerate(self.activities, start=1)
            if activity.attitude not in defined
        ]
        problems += [
            f"activity {number}: trigger '{activity.trigger.text}' names the target "
            f"'{activity.trigger.target}', which neither gnd_targets nor "
            "sat_targets defines"
            for number, activity in enumerate(self.activities, start=1)
            if activity.trigger.target is not None
            and activity.trigger.target not in targets
        ]
        return problems

    def _park_problems(self) -> list[str]:
        """
        Each park mode that no activity gives the platform, `slew` included when there
        are slews.
        """
        if self.spacecraft_model is None:
            return []
        modes = sorted({activity.mode.platform for activity in self.activities})
        if self.slew is not None:
            modes.append(SLEW)
        return [
            f"articulation '{name}': park names the mode '{mode}', which the "
            f"platform never has. It has: {modes}"
            for name, articulation in self.spacecraft_model.articulations.items()
            for mode in articulation.park
            if mode not in modes
        ]

    @model_validator(mode="after")
    def _check_together(self, info: ValidationInfo):
        """
        Checks the step against the duration, the names, and the park modes, which the
        Activity Designer skips.
        """
        problems = []
        if isinstance(self.duration, Quantity) and self.step >= self.duration:
            problems.append(
                f"step must be shorter than duration, got '{self.step}' "
                f"and '{self.duration}'"
            )
        problems += self._direction_problems()
        if not (info.context or {}).get("designer", False):
            problems += self._park_problems()
        if problems:
            raise ValueError("\n".join(problems))
        return self
