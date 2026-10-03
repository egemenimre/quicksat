# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The scenario file: the orbit, the period, the attitudes and the activities.

A scenario is one YAML file. It names the orbit and gives the start time and the
duration of the run. It also sets the axes of the two attitudes and lists the
activities. The list is written once, and the run repeats it until the duration
ends. Each activity is a short list of three or four strings:

    - [10 min, nadir, downlink, eclipse]

They are the trigger that ends the activity, the attitude, the mode, and an
optional constraint on the illumination. The activities form a chain. Each one
starts where the one before it ends, and the first starts at the start time.

This module reads and checks the file. It does not run anything.

"""

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Annotated, Literal, cast, get_args

import yaml
from astropy.time import Time
from astropy.units import Quantity
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from quicksat import Q_, u
from quicksat.utils.intervals import TIME_GRID
from quicksat.utils.parser_helpers import LengthQty, PlainQty, TimeQty

Axis = Literal["+x", "-x", "+y", "-y", "+z", "-z"]
"""A body axis, with its sign: the axis the attitude points along."""

Illumination = Literal["sunlit", "eclipse"]
"""The states of the illumination, and so the constraints an activity may have."""

EventName = Literal["eclipse entry", "eclipse exit"]
"""The events that can end an activity."""

EVENT_TRIGGERS: tuple[str, ...] = get_args(EventName)
"""The event triggers, as written in the scenario file."""

NADIR = "nadir"
"""Name of the attitude that points one body axis at the nadir."""

SUN_POINTING = "sun pointing"
"""Name of the attitude that points one body axis at the sun."""

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


class NadirAttitude(BaseModel):
    """
    The nadir attitude: one body axis points at the Earth.

    Parameters
    ----------
    nadir_axis : str
        The body axis that points at the nadir
    orbit_normal : str
        The body axis along the orbit normal. With `+z` and `-y` the body axes
        match LVLH: x along the track, y minus the orbit normal and z nadir.
    """

    model_config = ConfigDict(extra="forbid")

    nadir_axis: Axis
    orbit_normal: Axis

    @model_validator(mode="after")
    def _axes_differ(self):
        """Checks that the two axes use different body axes."""
        _different_axes(
            self.nadir_axis, self.orbit_normal, "nadir_axis and orbit_normal"
        )
        return self


class SunPointingAttitude(BaseModel):
    """
    The sun pointing attitude: one body axis points at the sun.

    A second axis is kept as close as the sun axis allows to one of two
    directions. Exactly one of `constrain_to_nadir` and `constrain_to_orbit_normal`
    is given.

    Parameters
    ----------
    sun_axis : str
        The body axis that points at the sun
    constrain_to_nadir : str, optional
        The body axis that keeps facing the Earth. The body spins fast about the
        sun axis when the sun comes close to the nadir line.
    constrain_to_orbit_normal : str, optional
        The body axis kept along the orbit normal. The body stays still over an
        orbit, and is undefined only at a beta of +-90 degrees.
    """

    model_config = ConfigDict(extra="forbid")

    sun_axis: Axis
    constrain_to_nadir: Axis | None = None
    constrain_to_orbit_normal: Axis | None = None

    @model_validator(mode="after")
    def _one_constraint(self):
        """Checks for exactly one constrained axis, on a different body axis."""
        given = {
            "constrain_to_nadir": self.constrain_to_nadir,
            "constrain_to_orbit_normal": self.constrain_to_orbit_normal,
        }
        chosen = {key: axis for key, axis in given.items() if axis is not None}
        if len(chosen) != 1:
            raise ValueError(
                "'sun pointing' needs exactly one of constrain_to_nadir and "
                f"constrain_to_orbit_normal, got {len(chosen)}"
            )
        ((key, axis),) = chosen.items()
        _different_axes(self.sun_axis, axis, f"sun_axis and {key}")
        return self


class Attitudes(BaseModel):
    """
    The attitudes the activities can name: `nadir`, `sun pointing`, or both.

    Parameters
    ----------
    nadir : NadirAttitude, optional
        The nadir attitude
    sun_pointing : SunPointingAttitude, optional
        The sun pointing attitude. Its key in the file is `sun pointing`, with a
        space.
    """

    model_config = ConfigDict(extra="forbid")

    nadir: NadirAttitude | None = None
    sun_pointing: SunPointingAttitude | None = Field(None, alias=SUN_POINTING)

    @model_validator(mode="after")
    def _at_least_one(self):
        """Checks that at least one attitude is defined."""
        if not self.names:
            raise ValueError(
                f"attitudes must define '{NADIR}', '{SUN_POINTING}' or both"
            )
        return self

    @property
    def names(self) -> list[str]:
        """
        The names of the attitudes that are defined, as the activities write them.

        Returns
        -------
        names : list of str
            `nadir` and `sun pointing`, as far as they are defined
        """
        defined = {NADIR: self.nadir, SUN_POINTING: self.sun_pointing}
        return [name for name, attitude in defined.items() if attitude is not None]


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


_CLOCK_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?")
"""A time of day written as hours and minutes, with seconds if wanted."""


def _parse_ltan(value) -> Quantity:
    """
    Pydantic BeforeValidator for the local time of the ascending node.

    Parameters
    ----------
    value : str or Quantity
        A time of day in quotes, such as `"10:30"` or `"10:30:15"`, or a time
        with a unit, such as `10.5 h`

    Returns
    -------
    ltan : Quantity
        The local time of the ascending node, in hours, from 0 to 24

    Raises
    ------
    ValueError
        If the value is a bare number, is not a time of day, or is not from 0 to
        24 h. YAML reads an unquoted `10:30` as the number 630, a base-60 number.
        So the error for a bare number says to add quotes.
    """
    example = 'such as "10:30" in quotes, or 10.5 h'
    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise ValueError(
            f"ltan must be a time of day, {example}. Got the bare number {value}. "
            "YAML reads an unquoted 10:30 as the number 630, so put it in quotes."
        )
    if isinstance(value, Quantity):
        hours = value
    elif isinstance(value, str):
        text = value.strip()
        match = _CLOCK_TIME.fullmatch(text)
        if match:
            hour, minute, second = match.groups()
            if int(minute) >= 60 or float(second or 0) >= 60:
                raise ValueError(f"ltan has more than 59 minutes or seconds: '{text}'")
            hours = Q_(int(hour) + int(minute) / 60 + float(second or 0) / 3600, "h")
        else:
            try:
                hours = Q_(text)
            except (TypeError, ValueError):
                raise ValueError(
                    f"ltan must be a time of day, {example}. Got '{text}'"
                ) from None
    else:
        raise ValueError(f"ltan must be a time of day, {example}. Got {value!r}")
    if not u.h.is_equivalent(hours.unit):
        raise ValueError(f"ltan must be a time of day, {example}. Got '{hours}'")
    hours = hours.to(u.h)
    if not Q_(0, "h") <= hours < Q_(24, "h"):
        raise ValueError(f"ltan must be from 0 to 24 h, got {hours}")
    return hours


class SsoOrbit(BaseModel):
    """
    A circular sun-synchronous orbit. quicksat builds its TLE.

    The TLE has its epoch at the start of the run. Its inclination makes SGP4's
    node rate match the mean sun. See `quicksat.orbit.sso`.

    Parameters
    ----------
    altitude : Quantity
        Distance from the centre of the Earth minus `R_EARTH`, averaged over one
        orbit. Positive.
    ltan : Quantity
        Local mean time of the ascending node, from 0 to 24 h. Written `"10:30"`,
        in quotes, or `10.5 h`.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    altitude: LengthQty
    ltan: Annotated[Quantity, BeforeValidator(_parse_ltan)]

    @field_validator("altitude")
    @classmethod
    def _positive_altitude(cls, value):
        """Checks that the altitude is above zero."""
        if value <= Q_(0, "km"):
            raise ValueError(f"altitude must be positive, got '{value}'")
        return value


class Orbit(BaseModel):
    """
    Where the orbit comes from: a TLE file, or a sun-synchronous orbit.

    Exactly one of the two is given.

    Parameters
    ----------
    tle_file : Path, optional
        A file with exactly one TLE. A relative path is taken from the folder of
        the scenario file.
    sso : SsoOrbit, optional
        A sun-synchronous orbit. quicksat builds its TLE, with the epoch at the
        start of the run.
    """

    model_config = ConfigDict(extra="forbid")

    tle_file: Path | None = None
    sso: SsoOrbit | None = None

    @model_validator(mode="before")
    @classmethod
    def _exactly_one_key(cls, data):
        """Checks that the orbit has exactly one key, and that it is accepted."""
        accepted = sorted(cls.model_fields)
        if not isinstance(data, dict):
            raise ValueError(f"orbit must have exactly one key, one of: {accepted}")
        keys = [str(key) for key in data]
        if len(keys) != 1 or keys[0] not in accepted:
            raise ValueError(
                f"orbit must have exactly one key, one of: {accepted}. Got: {keys}"
            )
        return data

    @field_validator("tle_file")
    @classmethod
    def _relative_to_the_file(
        cls, path: Path | None, info: ValidationInfo
    ) -> Path | None:
        """Takes a relative path from the folder of the scenario file."""
        base_dir = (info.context or {}).get("base_dir")
        if path is not None and base_dir is not None and not path.is_absolute():
            return Path(base_dir) / path
        return path


class Trigger(BaseModel):
    """
    What ends an activity: a duration, or an event.

    Build one with `parse_trigger`. Offsets and other events, such as a latitude
    crossing, come later. They will add fields here and forms to the parser.

    Parameters
    ----------
    text : str
        The trigger as written in the file, with the spaces tidied
    duration : Quantity, optional
        The length of the activity, for a duration trigger
    event : str, optional
        The event that ends the activity, for an event trigger
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    text: str
    duration: PlainQty | None = None
    event: EventName | None = None

    @model_validator(mode="after")
    def _duration_or_event(self):
        """Checks that the trigger has a duration or an event, and not both."""
        if (self.duration is None) == (self.event is None):
            raise ValueError("a trigger has either a duration or an event")
        return self


def _trigger_forms() -> str:
    """
    The accepted forms of a trigger, for the error message.

    Returns
    -------
    forms : str
        The forms in one sentence
    """
    events = " and ".join(f"'{event}'" for event in EVENT_TRIGGERS)
    return f"a positive duration with a unit, such as '20 min', or one of {events}"


def parse_trigger(text: str) -> Trigger:
    """
    Read a trigger, the first field of an activity.

    The accepted forms are a positive duration with a unit, such as `20 min`, and
    the events `eclipse entry` and `eclipse exit`. A duration must be at least as
    long as the 1 ms time grid.

    Parameters
    ----------
    text : str
        The trigger as written in the scenario file

    Returns
    -------
    trigger : Trigger
        The parsed trigger

    Raises
    ------
    ValueError
        If the text is none of the accepted forms. The message names them.
    """
    if not isinstance(text, str):
        raise ValueError(f"trigger {text!r} is not text. Use {_trigger_forms()}")
    tidy = " ".join(text.split())
    for event in get_args(EventName):
        if tidy.lower() == event:
            return Trigger(text=tidy, event=event)

    try:
        duration = Q_(tidy)
    # astropy raises a TypeError when the text does not start with a number, and a
    # ValueError for an unknown unit
    except (TypeError, ValueError):
        raise ValueError(
            f"trigger '{tidy}' is not understood. Use {_trigger_forms()}"
        ) from None
    if not cast(u.UnitBase, duration.unit).is_equivalent(u.s):
        raise ValueError(f"trigger '{tidy}' is not a time. Use {_trigger_forms()}")
    if duration < TIME_GRID:
        raise ValueError(
            f"trigger '{tidy}' must be positive, and at least {TIME_GRID}, the time grid"
        )
    return Trigger(text=tidy, duration=duration)


def parse_constraint(text: str) -> Illumination:
    """
    Read a constraint, the optional last field of an activity.

    Parameters
    ----------
    text : str
        `sunlit` or `eclipse`

    Returns
    -------
    constraint : str
        The constraint, in lower case

    Raises
    ------
    ValueError
        If the text is not `sunlit` or `eclipse`. `umbra` and `penumbra` get a
        message that they come with the penumbra model.
    """
    if not isinstance(text, str):
        raise ValueError(f"constraint {text!r} is not text. Use 'sunlit' or 'eclipse'")
    word = text.strip().lower()
    if word in ("umbra", "penumbra"):
        raise ValueError(
            f"constraint '{word}' comes with the penumbra, which is not modelled "
            "yet. Use 'sunlit' or 'eclipse'"
        )
    for constraint in get_args(Illumination):
        if word == constraint:
            return constraint
    raise ValueError(
        f"constraint '{text}' is not understood. Use 'sunlit' or 'eclipse'"
    )


class Activity(BaseModel):
    """
    One activity: what ends it, how the satellite points, and what it does.

    Parameters
    ----------
    trigger : Trigger
        What ends the activity
    attitude : str
        The name of the attitude, which must be one of the scenario's attitudes
    mode : str
        The name of the mode. Any name that is not empty.
    constraint : str, optional
        The illumination the activity expects, `sunlit` or `eclipse`
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    trigger: Trigger
    attitude: str
    mode: str
    constraint: Illumination | None = None

    @classmethod
    def from_fields(cls, fields) -> "Activity":
        """
        Build an activity from its list of strings, as written in the file.

        Parameters
        ----------
        fields : list of str
            The trigger, the attitude, the mode and an optional constraint

        Returns
        -------
        activity : Activity
            The checked activity

        Raises
        ------
        ValueError
            If the list has the wrong length or a field is not valid
        """
        if not isinstance(fields, (list, tuple)) or len(fields) not in (3, 4):
            raise ValueError(
                "an activity is a list of three or four items: the trigger, "
                f"the attitude, the mode and an optional constraint. Got {fields!r}"
            )
        names = ("attitude", "mode")
        for name, value in zip(names, fields[1:3], strict=True):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"the {name} must be a name in text that is not empty, got {value!r}"
                )
        return cls(
            trigger=parse_trigger(fields[0]),
            attitude=fields[1].strip(),
            mode=fields[2].strip(),
            constraint=parse_constraint(fields[3]) if len(fields) == 4 else None,
        )


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


class Scenario(BaseModel):
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
    attitudes : Attitudes
        The two attitudes the activities can name
    activities : list of Activity
        One repeat of the activities. The run repeats the list until the duration
        ends, and cuts the last activity there.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    orbit: Orbit
    start: Annotated[Time, BeforeValidator(_parse_start)]
    duration: Annotated[Quantity | OrbitCount, BeforeValidator(_parse_duration)]
    step: TimeQty = DEFAULT_STEP
    attitudes: Attitudes
    activities: list[Activity]

    @classmethod
    def from_yaml_file(cls, file_path: str | Path) -> "Scenario":
        """
        Initialise the scenario from a YAML file.

        A relative TLE path is taken from the folder of the YAML file.

        Parameters
        ----------
        file_path : str | Path
            Filepath containing the scenario (YAML)

        Returns
        -------
        scenario : Scenario
            Scenario object from the input data
        """
        if not file_path:
            raise ValueError("Path is None. No file to be found.")
        elif not os.path.isfile(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")
        else:
            path = Path(file_path)
            with open(path, "rt") as file:
                return cls.from_yaml_text(file.read(), base_dir=path.parent)

    @classmethod
    def from_yaml_text(
        cls, yaml_text: str, base_dir: str | Path | None = None
    ) -> "Scenario":
        """
        Initialise the scenario from YAML text.

        Parameters
        ----------
        yaml_text : str
            Text containing the scenario (YAML)
        base_dir : str | Path, optional
            The folder a relative TLE path is taken from. Without it, the path
            stays relative to the working directory.

        Returns
        -------
        scenario : Scenario
            Scenario object from the input data
        """
        if not yaml_text:
            raise ValueError("Text content is None.")
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            raise ValueError("A scenario file must be a mapping of keys to values.")
        return cls.model_validate(data, context={"base_dir": base_dir})

    @field_validator("step")
    @classmethod
    def _positive(cls, value, info: ValidationInfo):
        """Checks that the step is above zero."""
        if value <= Q_(0, "s"):
            raise ValueError(f"{info.field_name} must be positive, got '{value}'")
        return value

    @field_validator("activities", mode="before")
    @classmethod
    def _read_activities(cls, value):
        """
        Reads every activity, and names it by its number in the list on an error.
        """
        if not isinstance(value, list) or not value:
            raise ValueError("activities must be a list of at least one activity")
        activities, problems = [], []
        for number, fields in enumerate(value, start=1):
            try:
                activities.append(Activity.from_fields(fields))
            except ValueError as exc:
                problems.append(f"activity {number}: {exc}")
        if problems:
            raise ValueError("\n".join(problems))
        return activities

    @model_validator(mode="after")
    def _check_together(self):
        """
        Checks what spans fields: the step against the duration, and the names.

        A duration in orbits is checked against the step only when the run
        starts, once the nodal period is known.
        """
        problems = []
        if isinstance(self.duration, Quantity) and self.step >= self.duration:
            problems.append(
                f"step must be shorter than duration, got '{self.step}' "
                f"and '{self.duration}'"
            )
        defined = self.attitudes.names
        for number, activity in enumerate(self.activities, start=1):
            if activity.attitude not in defined:
                problems.append(
                    f"activity {number}: attitude '{activity.attitude}' is not "
                    f"defined in attitudes, which define: {defined}"
                )
        if problems:
            raise ValueError("\n".join(problems))
        return self
