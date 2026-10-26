# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The scenario file: the orbit, the period, the attitudes and the activities.

A scenario is one YAML file. It names the orbit and gives the start time and the
duration of the run. It also defines the attitudes, and lists the activities.
The list is written once, and the run repeats it until the duration ends. Each
activity is a short list of four or five items:

    - [downlink pass, 10 min, nadir, {payload_mode: downlink, platform_mode: ttc}, eclipse]

They are the title, which names what the activity is for, the trigger that ends
the activity, the attitude, the modes, and an optional constraint on the
illumination. The modes are two: the payload's, and the platform's that carries
it. A third, optional key says which activity's mode the payload is in during
the slew into this one. The activities form a chain. Each one starts where the
one before it ends, and the first starts at the start time.

An activity may also be written as a mapping with the same fields named, which
leaves room for its comments:

    - title: downlink pass
      end: 10 min
      attitude: nadir
      mode: {payload_mode: downlink, platform_mode: ttc}
      comments: The X-band antenna is on +z.

Every block of the file may hold the user's own notes in a `comments` field, and
so may the file as a whole. The sections of named items, such as `attitudes`,
may hold one too, so no item may be named `comments`.

This module reads and checks the file. It does not run anything. The file's
parts have modules of their own: the orbit and the targets in `orbit_config`,
the triggers in `triggers`, the activities in `activities`, and the names they
share in `names`.

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
    """
    Check that two axes of one attitude use different body axes.

    Parameters
    ----------
    first, second : str
        Axes such as `+z` and `-y`
    names : str
        What the two axes are, for the error message

    Raises
    ------
    ValueError
        If both axes use the same letter, whatever their signs
    """
    if first[1] == second[1]:
        raise ValueError(
            f"{names} must use different body axes, got '{first}' and '{second}'"
        )


def _read_pair(value) -> tuple[str, str]:
    """
    An `[axis, direction]` pair, as the file writes it.

    Parameters
    ----------
    value : list
        The pair, such as `[+z, nadir]`

    Returns
    -------
    pair : tuple of str
        The axis and the direction, without the spaces at their ends

    Raises
    ------
    ValueError
        If the value is not a list of two strings
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
    The turns of an attitude's offset, as the file writes them.

    Parameters
    ----------
    value : list of str or None
        Turns such as `x 30 deg`: a body axis and an angle

    Returns
    -------
    turns : list of tuple
        The axis, `x`, `y` or `z`, and the angle in degrees, in order

    Raises
    ------
    ValueError
        If the value is not a list, or a turn is not an axis and an angle
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
    An attitude: one body axis fixed on a direction, and a second body axis
    turned as close as it can get to another direction.

    A direction is one of `DIRECTIONS`, or a target that the scenario names in
    `gnd_targets` or `sat_targets`.

    Parameters
    ----------
    point : tuple of str
        The body axis and the direction it is fixed on, written `[+z, nadir]`
    constrain : tuple of str
        The second body axis and the direction it turns as close as it can get
        to, written `[-y, orbit normal]`. It must use a different body axis.
    fallback : str, optional
        The direction that takes the constraint's place where the constraint's
        direction is parallel to the pointed one. By default, the first of
        `FALLBACKS` that the attitude does not use.
    offset : list, optional
        Turns about the body axes, applied in order after the orientation above,
        written `[x 30 deg]`. Each is right-handed, about the body's own axis as
        the turns before it left it.
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
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
        The direction that replaces the constraint's where it is parallel to the
        pointed one.

        Returns
        -------
        direction : str
            `fallback`, or by default the first of `FALLBACKS` that the attitude
            does not use
        """
        if self.fallback is not None:
            return self.fallback
        used = {self.point[1], self.constrain[1]}
        return next(direction for direction in FALLBACKS if direction not in used)

    @property
    def directions(self) -> list[str]:
        """
        Every direction the attitude uses: the pointed one, the constraint's, and
        the fallback.

        Returns
        -------
        directions : list of str
        """
        return [self.point[1], self.constrain[1], self.fallback_direction]


_ORBIT_COUNT = re.compile(r"(\d+(?:\.\d*)?|\.\d+)\s*orbits?", re.IGNORECASE)
"""A duration written as a number of orbits, such as `3 orbits` or `1 orbit`."""


@dataclass(frozen=True)
class OrbitCount:
    """
    A duration given as a number of orbits.

    One orbit is the nodal period of the element set: the time from one ascending
    node to the next. The run turns the count into a time once the element set is
    known.

    Parameters
    ----------
    count : float
        The number of orbits, positive. It need not be whole.
    """

    count: float

    def __str__(self) -> str:
        """The count as written in a scenario file, such as `3 orbits`."""
        return f"{self.count:g} orbit{'' if self.count == 1 else 's'}"


def _parse_duration(value) -> Quantity | OrbitCount:
    """
    Pydantic BeforeValidator for the duration of the run.

    Parameters
    ----------
    value : str or Quantity
        A time with a unit, such as `5 h`, or a number of orbits, such as
        `3 orbits`

    Returns
    -------
    duration : Quantity or OrbitCount
        The time, or the number of orbits

    Raises
    ------
    ValueError
        If the value is neither, or is not positive
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
    Pydantic BeforeValidator for the start time.

    Parameters
    ----------
    value : str or datetime or Time
        An ISO time such as `2026-10-01T00:00:00`, in UTC. YAML turns an unquoted
        one into a `datetime` with no time zone. A time zone is converted to UTC,
        and a date alone means midnight.

    Returns
    -------
    start : Time
        The start time, in the UTC time scale

    Raises
    ------
    ValueError
        If the value is not an ISO time
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
    How the body turns from one attitude to another.

    A slew turns from rest to rest about one axis. It speeds up at the maximum
    acceleration, coasts at the maximum rate if it reaches it, and slows down
    again. The body then settles for the settling time before the activity
    starts. The same rate and acceleration hold for every axis. They can be set
    close to the agility budget's, but nothing reads them from it.

    Parameters
    ----------
    max_rate : Quantity, optional
        The fastest the body turns, such as `0.7 deg/s`. Without it, the slew
        speeds up until the midpoint, then slows down.
    max_acceleration : Quantity, optional
        How fast the turn speeds up and slows down, such as `0.08 deg/s2`.
        Without it, the slew starts and stops at the maximum rate at once.
    settling_time : Quantity, optional
        Time to settle after the turn, 0 s by default
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    max_rate: AngularRateQty | None = None
    max_acceleration: AngularAccelerationQty | None = None
    settling_time: TimeQty = Q_(0, "s")

    @model_validator(mode="after")
    def _a_positive_limit(self):
        """Checks for at least one limit, and that each limit is above zero."""
        limits = {"max_rate": self.max_rate, "max_acceleration": self.max_acceleration}
        given = {name: limit for name, limit in limits.items() if limit is not None}
        if not given:
            raise ValueError("a slew needs max_rate, max_acceleration, or both")
        for name, limit in given.items():
            if limit <= 0:
                raise ValueError(f"{name} must be positive, got '{limit}'")
        return self

    def _limits(self) -> tuple[float | None, float | None]:
        """
        The two limits as plain numbers, in rad/s and rad/s^2.

        Returns
        -------
        limits : tuple
            The maximum rate and the maximum acceleration, or None for either
        """
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
            In seconds
        """
        seconds = slew_duration(np.asarray(angle.to(u.rad).value), *self._limits())
        return Q_(float(seconds), "s")

    def turned(self, angle: Quantity, elapsed: Quantity) -> np.ndarray:
        """
        How far through the turn the body is, as a fraction.

        Parameters
        ----------
        angle : Quantity
            The whole angle of the turn
        elapsed : Quantity
            Time since the turn started, one value or an array

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
    A part of the 3D model that turns about one body axis, such as a solar wing
    that follows the sun.

    At each step, the part turns about `axis` until the axis that `point` names
    is as close to its direction as the turn allows. The angle is zero where the
    model draws the part, and turns right-handed about the axis. In a platform
    mode that `park` names, the part holds the angle given there instead.

    Parameters
    ----------
    part : str
        The name of the GLB node that turns. It turns about the axis through its
        own origin, and its children turn with it.
    axis : str
        The drive axis, in body axes, such as `+y`
    point : tuple of str
        The part's axis, as the model draws the part, and the direction to turn
        it toward, written `[-z, sun]`. The direction is one an attitude can
        use: a built-in direction, or a target named in `gnd_targets` or
        `sat_targets`. The
        axis must use a different body axis from `axis`.
    range : tuple of Quantity, optional
        The lowest and the highest angle, from -180 to 180 degrees. All the way
        round by default. Where the direction asks for an angle outside it, the
        part stops at the nearer end.
    park : dict of str to Quantity, optional
        A fixed angle for each platform mode named, inside the range
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    part: str
    axis: Axis
    point: AxisPair
    range: tuple[SignedAngleQty, SignedAngleQty] = FULL_TURN
    park: dict[str, SignedAngleQty] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self):
        """Checks the axes, the range, and that each park angle is in the range."""
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
    """A `3d_model` given as a file name, as the mapping with only `file`."""
    if isinstance(value, (str, Path)):
        return {"file": value}
    return value


class SpacecraftModel(Commented):
    """
    The spacecraft's 3D model, and the parts of it that turn.

    `3d_model` in the scenario file is either the name of the GLB file, or a
    mapping with `file` and `articulations`.

    Parameters
    ----------
    file : Path
        The GLB file, in body axes and metres. A relative path is taken from the
        folder of the scenario file.
    articulations : dict of str to Articulation, optional
        The parts that turn, each under a name of your choice
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
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
        Start of the run, in UTC. An ISO string, or the datetime that YAML makes
        of an unquoted ISO time.
    duration : Quantity or OrbitCount
        Length of the run, positive: a time such as `5 h`, or a number of orbits
        such as `3 orbits`. One orbit is the nodal period of the element set.
    step : Quantity
        Time step of the grid that the orbit is evaluated on. Positive, shorter
        than the duration, and 10 s by default.
    gnd_targets : dict of str to GroundTarget, optional
        Ground points, by name, that an attitude can point at
    sat_targets : dict of str to SatelliteTarget, optional
        Other satellites, by name, that an attitude can point at. No name may be
        in both blocks.
    attitudes : dict of str to Attitude
        The attitudes the activities can name, by a name of your choice. At
        least one, and none named `slew` or `unplanned`.
    activities : list of Activity
        One repeat of the activities, at least one. The run repeats the list
        until the duration ends, and cuts the last activity there. The Activity
        Designer reads a scenario with `designer`, which allows an empty list.
    slew : Slew, optional
        How the body turns between attitudes. Without it, attitude changes are
        instant.
    spacecraft_model : SpacecraftModel, optional
        The spacecraft's 3D model, written `3d_model` in the file: a GLB file in
        body axes and metres, and the parts of it that turn. The viewer draws it,
        or a 1 m cube without it.
    comments : str, optional
        Your own notes on the whole file. quicksat keeps them and does not read
        them.
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
        Initialise the scenario from a YAML file.

        A relative TLE path is taken from the folder of the YAML file.

        Parameters
        ----------
        file_path : str | Path
            Filepath containing the scenario (YAML)
        designer : bool, optional
            Read the file as the Activity Designer does: see `from_yaml_text`

        Returns
        -------
        scenario : Scenario
            Scenario object from the input data
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
        Initialise the scenario from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the scenario (YAML)
        base_dir : str | Path, optional
            The folder a relative TLE path is taken from. Without it, the path
            stays relative to the working directory.
        designer : bool, optional
            Read the text as the Activity Designer does, for a list of activities
            still being built. The list may then be empty, and a park mode need
            not be one that the activities have yet. Every other check stays.

        Returns
        -------
        scenario : Scenario
            Scenario object from the input data
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
        Takes a relative path from the folder of the scenario file, checks that
        the viewer can read the model, and that each articulation names one of
        its nodes.
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
        """Checks that there is an attitude, and that each name can be used."""
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
        """
        Reads every activity, in the list form or the map form, and names it by
        its number in the list on an error. The list may be empty only in the
        Activity Designer, where a key with no value is an empty list too.
        """
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
        Problems with the names: a target named as a built-in direction, a name
        in both target blocks, an attitude or an articulation with a direction
        that is neither, an activity's attitude that is not defined, and a rise
        or set of a target that is not defined.

        Returns
        -------
        problems : list of str
            One message for each problem
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
        Problems with the articulations: a park mode that no activity gives the
        platform. The park angles go by the platform's mode, since the drives are
        platform equipment.

        `slew` counts as a mode when the scenario has slews, since the platform
        takes it while the body turns.

        Returns
        -------
        problems : list of str
            One message for each problem
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
        Checks what spans fields: the step against the duration, the names and
        the directions, and the park modes. The Activity Designer skips the park
        modes, as its list may not have them yet.

        A duration in orbits is checked against the step only when the run
        starts, once the nodal period is known.
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
