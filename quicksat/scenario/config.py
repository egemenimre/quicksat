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
activity is a short list of three or four strings:

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

import numpy as np
import yaml
from astropy.time import Time
from astropy.units import Quantity
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from quicksat import Q_, u
from quicksat.orbit.attitude import slew_duration, slew_progress
from quicksat.scenario.spacecraft import node_index, read_glb_json
from quicksat.utils.intervals import TIME_GRID
from quicksat.utils.parser_helpers import (
    AngularAccelerationQty,
    AngularRateQty,
    LengthQty,
    PlainQty,
    SignedAngleQty,
    SignedLengthQty,
    TimeQty,
)

Axis = Literal["+x", "-x", "+y", "-y", "+z", "-z"]
"""A body axis, with its sign: the axis the attitude points along."""

Illumination = Literal["sunlit", "penumbra", "umbra", "eclipse"]
"""The constraints an activity may have. The illumination has three states,
`sunlit`, `penumbra` and `umbra`, and `eclipse` means either of the last two."""

EventName = Literal[
    "eclipse entry",
    "eclipse exit",
    "umbra entry",
    "umbra exit",
    "latitude crossing",
    "rise",
    "set",
]
"""The kinds of event that can end an activity."""

LATITUDE_CROSSING = "latitude crossing"
"""The event of a latitude trigger, and of the node triggers."""

RISE = "rise"
"""The event of a ground target rising above its minimum elevation."""

SET = "set"
"""The event of a ground target setting below its minimum elevation."""

Direction = Literal["ascending", "descending"]
"""The direction of a latitude crossing: northward or southward."""

NODES: dict[str, Direction] = {
    "ascending node": "ascending",
    "descending node": "descending",
}
"""The node triggers, and the direction of their crossing of the equator."""

NADIR = "nadir"
"""Direction: toward the centre of the Earth."""

SUN = "sun"
"""Direction: toward the sun, as seen from the satellite."""

ORBIT_NORMAL = "orbit normal"
"""Direction: the position crossed with the velocity."""

VELOCITY = "velocity"
"""Direction: the inertial velocity, in GCRS."""

GROUND_VELOCITY = "ground velocity"
"""Direction: the velocity relative to the turning Earth, for yaw steering in
imaging."""

DIRECTIONS = (NADIR, SUN, ORBIT_NORMAL, VELOCITY, GROUND_VELOCITY)
"""The built-in directions. A ground point named in `targets` is a direction too."""

FALLBACKS = (ORBIT_NORMAL, NADIR, VELOCITY)
"""The default fallback is the first of these that the attitude does not use."""

SLEW = "slew"
"""The value of the attitude row while the body turns or settles. No attitude may
take this name."""

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


class Attitude(BaseModel):
    """
    An attitude: one body axis fixed on a direction, and a second body axis
    turned as close as it can get to another direction.

    A direction is one of `DIRECTIONS`, or a ground point that the scenario names
    in `targets`.

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


class GroundTarget(BaseModel):
    """
    A point on the ground, which turns with the Earth. An attitude can point at it.

    Parameters
    ----------
    latitude : Quantity
        Geodetic latitude, from -90 to 90 degrees
    longitude : Quantity
        Longitude, east
    altitude : Quantity, optional
        Height above the WGS84 ellipsoid, 0 m by default
    min_elevation : Quantity, optional
        The elevation above the point's horizon at which the satellite rises
        and sets, for the `rise` and `set` triggers. 5 deg by default.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    latitude: SignedAngleQty
    longitude: SignedAngleQty
    altitude: SignedLengthQty = Q_(0, "m")
    min_elevation: SignedAngleQty = Q_(5, "deg")

    @model_validator(mode="after")
    def _check(self):
        """Checks the latitude and the minimum elevation."""
        if abs(self.latitude) > Q_(90, "deg"):
            raise ValueError(
                f"latitude must be from -90 to 90 deg, got '{self.latitude}'"
            )
        if not Q_(0, "deg") <= self.min_elevation < Q_(90, "deg"):
            raise ValueError(
                f"min_elevation must be from 0 deg up to 90 deg, got "
                f"'{self.min_elevation}'"
            )
        return self


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
    Where the orbit comes from: a TLE file, an OMM file, a sun-synchronous
    orbit, or a trajectory file.

    Exactly one of the four is given.

    Parameters
    ----------
    tle_file : Path, optional
        A file with exactly one TLE. A relative path is taken from the folder of
        the scenario file.
    omm_file : Path, optional
        A file with exactly one OMM element set, in KVN, XML, JSON or CSV. See
        `quicksat.orbit.omm`. A relative path is taken from the folder of the
        scenario file.
    sso : SsoOrbit, optional
        A sun-synchronous orbit. quicksat builds its TLE, with the epoch at the
        start of the run.
    trajectory_file : Path, optional
        A file of positions and velocities, which the run interpolates: ECSV,
        or a CCSDS OEM in KVN. See `quicksat.orbit.trajectory_files`. A
        relative path is taken from the folder of the scenario file.
    """

    model_config = ConfigDict(extra="forbid")

    tle_file: Path | None = None
    omm_file: Path | None = None
    sso: SsoOrbit | None = None
    trajectory_file: Path | None = None

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

    @field_validator("tle_file", "omm_file", "trajectory_file")
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
    What ends an activity: a duration, or an event with an optional offset.

    Build one with `parse_trigger`.

    Parameters
    ----------
    text : str
        The trigger as written in the file, with the spaces tidied
    duration : Quantity, optional
        The length of the activity, for a duration trigger
    event : str, optional
        The kind of event that ends the activity, for an event trigger:
        `eclipse entry`, `eclipse exit`, `umbra entry`, `umbra exit`,
        `latitude crossing`, `rise` or `set`. The node triggers are latitude
        crossings of 0 degrees.
    latitude : Quantity, optional
        The geodetic latitude crossed, from -90 to 90 degrees, for a latitude
        crossing
    direction : str, optional
        `ascending` for a northward crossing, `descending` for a southward one,
        or None for either. Only for a latitude crossing.
    target : str, optional
        The ground target that rises or sets, by its name in `targets`. Only for
        a `rise` or a `set`.
    offset : Quantity, optional
        Time added to the event, negative to end the activity before it. Only for
        an event trigger.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    text: str
    duration: PlainQty | None = None
    event: EventName | None = None
    latitude: PlainQty | None = None
    direction: Direction | None = None
    target: str | None = None
    offset: PlainQty | None = None

    @model_validator(mode="after")
    def _consistent(self):
        """Checks that the fields given suit a duration or an event."""
        if (self.duration is None) == (self.event is None):
            raise ValueError("a trigger has either a duration or an event")
        if (self.event == LATITUDE_CROSSING) != (self.latitude is not None):
            raise ValueError(
                "a latitude is given with a latitude crossing, and only then"
            )
        if self.direction is not None and self.event != LATITUDE_CROSSING:
            raise ValueError("only a latitude crossing has a direction")
        if (self.event in (RISE, SET)) != (self.target is not None):
            raise ValueError("a target is given with a rise or a set, and only then")
        if self.offset is not None and self.event is None:
            raise ValueError("only an event trigger has an offset")
        return self

    @property
    def event_key(self) -> tuple | None:
        """
        What the event is, without the offset, as a key for a lookup table.

        Returns
        -------
        key : tuple or None
            The kind of event, then the latitude in degrees and the direction for
            a latitude crossing, or the target for a rise or a set. None for a
            duration trigger.
        """
        if self.event is None:
            return None
        if self.event in (RISE, SET):
            return (self.event, self.target)
        if self.event == LATITUDE_CROSSING:
            assert self.latitude is not None  # checked when the trigger is built
            return (self.event, float(self.latitude.to(u.deg).value), self.direction)
        return (self.event,)


_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)"
"""A number without a sign, such as `30`, `2.5` or `.5`."""

_EVENT_TRIGGER = re.compile(
    r"(?P<event>eclipse entry|eclipse exit|umbra entry|umbra exit"
    r"|ascending node|descending node"
    rf"|latitude (?P<latitude>[+-]?{_NUMBER} ?[a-z]+)"
    r"(?: (?P<direction>ascending|descending))?)"
    rf"(?: ?(?P<sign>[+-]) ?(?P<offset>{_NUMBER}.*))?",
    re.IGNORECASE,
)
"""An event trigger, with an optional offset, in text whose spaces are tidied."""

_VISIBILITY_TRIGGER = re.compile(
    r"(?P<target>.+?) (?P<edge>rise|set)"
    rf"(?: ?(?P<sign>[+-]) ?(?P<offset>{_NUMBER}.*))?",
    re.IGNORECASE,
)
"""A ground target's rise or set, such as `Svalbard rise`, with an optional
offset. The target's name keeps its case, and may hold spaces."""


def _trigger_forms() -> str:
    """
    The accepted forms of a trigger, for the error message.

    Returns
    -------
    forms : str
        The forms in one sentence
    """
    return (
        "a positive duration with a unit, such as '20 min', or an event: "
        "'eclipse entry', 'eclipse exit', 'umbra entry', 'umbra exit', "
        "'ascending node', 'descending node', a "
        "latitude crossing such as 'latitude 30 deg ascending', or a target's rise "
        "or set, such as 'Svalbard rise'. An event can take an offset, such as "
        "'eclipse entry + 2 min'"
    )


def _parse_latitude(text: str, trigger: str) -> Quantity:
    """
    Read the latitude of a latitude trigger.

    Parameters
    ----------
    text : str
        An angle with a unit, such as `30 deg` or `-45.5 deg`
    trigger : str
        The whole trigger, for the error message

    Returns
    -------
    latitude : Quantity
        The latitude, in degrees

    Raises
    ------
    ValueError
        If the text is not an angle, or is not from -90 to 90 degrees
    """
    try:
        latitude = Q_(text)
    except (TypeError, ValueError):
        latitude = None
    if latitude is None or not cast(u.UnitBase, latitude.unit).is_equivalent(u.deg):
        raise ValueError(
            f"trigger '{trigger}' needs a latitude with an angle unit, such as "
            "'latitude 30 deg ascending'"
        )
    latitude = latitude.to(u.deg)
    if abs(latitude) > Q_(90, "deg"):
        raise ValueError(
            f"trigger '{trigger}' needs a latitude from -90 to 90 deg, got {latitude}"
        )
    return latitude


def _parse_offset(sign: str, text: str, trigger: str) -> Quantity:
    """
    Read the offset of an event trigger.

    Parameters
    ----------
    sign : str
        `+` or `-`
    text : str
        A time with a unit and no sign, such as `2 min`
    trigger : str
        The whole trigger, for the error message

    Returns
    -------
    offset : Quantity
        The offset, negative for `-`

    Raises
    ------
    ValueError
        If the text is not a time with a unit
    """
    try:
        offset = Q_(text)
    except (TypeError, ValueError):
        offset = None
    if offset is None or not cast(u.UnitBase, offset.unit).is_equivalent(u.s):
        raise ValueError(
            f"trigger '{trigger}' has an offset that is not a time with a unit. "
            "Write it such as 'eclipse entry + 2 min'"
        )
    return -offset if sign == "-" else offset


def _event_trigger(tidy: str) -> Trigger | None:
    """
    Read an event trigger, if the text is one.

    Parameters
    ----------
    tidy : str
        The trigger, with its spaces tidied

    Returns
    -------
    trigger : Trigger or None
        The trigger, or None if the text is not an event trigger
    """
    match = _EVENT_TRIGGER.fullmatch(tidy)
    if match:
        name = match["event"].lower()
        offset = None
        if match["sign"]:
            offset = _parse_offset(match["sign"], match["offset"], tidy)
        if name in NODES:
            return Trigger(
                text=tidy,
                event=LATITUDE_CROSSING,
                latitude=Q_(0, "deg"),
                direction=NODES[name],
                offset=offset,
            )
        if match["latitude"]:
            direction = match["direction"]
            return Trigger(
                text=tidy,
                event=LATITUDE_CROSSING,
                latitude=_parse_latitude(match["latitude"], tidy),
                direction=cast(Direction, direction.lower()) if direction else None,
                offset=offset,
            )
        return Trigger(text=tidy, event=cast(EventName, name), offset=offset)
    match = _VISIBILITY_TRIGGER.fullmatch(tidy)
    if match:
        offset = None
        if match["sign"]:
            offset = _parse_offset(match["sign"], match["offset"], tidy)
        return Trigger(
            text=tidy,
            event=cast(EventName, match["edge"].lower()),
            target=match["target"],
            offset=offset,
        )
    return None


def parse_trigger(text: str) -> Trigger:
    """
    Read a trigger, the first field of an activity.

    The accepted forms are:

    - a positive duration with a unit, such as `20 min`. It must be at least as
      long as the 1 ms time grid.
    - the shadow edges `eclipse entry`, `umbra entry`, `umbra exit` and
      `eclipse exit`;
    - a latitude crossing, such as `latitude 30 deg ascending`, `latitude -30 deg
      descending`, or `latitude 45 deg` for either direction;
    - `ascending node` and `descending node`, the crossings of 0 degrees;
    - a ground target's rise or set, such as `Svalbard rise` or `Svalbard set`:
      the satellite passing above or below the target's minimum elevation. The
      target must be one that the scenario names in `targets`.
    - any of these events with an offset, such as `eclipse entry + 2 min` or
      `descending node - 30 s`.

    The words may be in any case, except a target's name.

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

    trigger = _event_trigger(tidy)
    if trigger is not None:
        return trigger
    if tidy.lower().startswith("latitude"):
        raise ValueError(
            f"trigger '{tidy}' is not understood. Write a latitude crossing such as "
            "'latitude 30 deg ascending', 'latitude -30 deg descending' or "
            "'latitude 30 deg' for either direction"
        )

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
        `sunlit`, `penumbra`, `umbra`, or `eclipse` for either of the last two

    Returns
    -------
    constraint : str
        The constraint, in lower case

    Raises
    ------
    ValueError
        If the text is none of the four words
    """
    words = ", ".join(f"'{word}'" for word in get_args(Illumination))
    if not isinstance(text, str):
        raise ValueError(f"constraint {text!r} is not text. Use one of {words}")
    word = text.strip().lower()
    for constraint in get_args(Illumination):
        if word == constraint:
            return constraint
    raise ValueError(f"constraint '{text}' is not understood. Use one of {words}")


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
        The illumination the activity expects: `sunlit`, `penumbra`, `umbra`,
        or `eclipse` for either of the last two
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


class Slew(BaseModel):
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


class Articulation(BaseModel):
    """
    A part of the 3D model that turns about one body axis to face the sun.

    At each step, the part turns about `axis` until `sun_axis` points as close to
    the sun as the turn allows. The angle is zero where the model draws the part,
    and turns right-handed about the axis. In a mode that `park` names, the part
    holds the angle given there instead.

    Parameters
    ----------
    part : str
        The name of the GLB node that turns. It turns about the axis through its
        own origin, and its children turn with it.
    axis : str
        The drive axis, in body axes, such as `+y`
    sun_axis : str
        The part's axis to turn to the sun, as the model draws the part. It must
        use a different body axis from `axis`.
    range : tuple of Quantity, optional
        The lowest and the highest angle, from -180 to 180 degrees. All the way
        round by default. Where the sun asks for an angle outside it, the part
        stops at the nearer end.
    park : dict of str to Quantity, optional
        A fixed angle for each mode named, inside the range
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    part: str
    axis: Axis
    sun_axis: Axis
    range: tuple[SignedAngleQty, SignedAngleQty] = FULL_TURN
    park: dict[str, SignedAngleQty] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self):
        """Checks the axes, the range, and that each park angle is in the range."""
        _different_axes(self.axis, self.sun_axis, "axis and sun_axis")
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


class SpacecraftModel(BaseModel):
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
        The parts that turn to face the sun, each under a name of your choice
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    file: Path
    articulations: dict[str, Articulation] = Field(default_factory=dict)


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
    targets : dict of str to GroundTarget, optional
        Ground points, by name, that an attitude can point at
    attitudes : dict of str to Attitude
        The attitudes the activities can name, by a name of your choice. At
        least one, and none named `slew`.
    activities : list of Activity
        One repeat of the activities. The run repeats the list until the duration
        ends, and cuts the last activity there.
    slew : Slew, optional
        How the body turns between attitudes. Without it, attitude changes are
        instant.
    spacecraft_model : SpacecraftModel, optional
        The spacecraft's 3D model, written `3d_model` in the file: a GLB file in
        body axes and metres, and the parts of it that turn. The viewer draws it,
        or a 1 m cube without it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    orbit: Orbit
    start: Annotated[Time, BeforeValidator(_parse_start)]
    duration: Annotated[Quantity | OrbitCount, BeforeValidator(_parse_duration)]
    step: TimeQty = DEFAULT_STEP
    targets: dict[str, GroundTarget] = Field(default_factory=dict)
    attitudes: dict[str, Attitude]
    activities: list[Activity]
    slew: Slew | None = None
    spacecraft_model: Annotated[
        SpacecraftModel | None, BeforeValidator(_model_mapping)
    ] = Field(None, alias="3d_model")

    _source_file: Path | None = PrivateAttr(None)
    _source_text: str | None = PrivateAttr(None)

    @property
    def source_file(self) -> Path | None:
        """
        The file the scenario was read from.

        Returns
        -------
        path : Path or None
            The path given to `from_yaml_file`, or None if the scenario was not
            read from a file
        """
        return self._source_file

    @property
    def source_text(self) -> str | None:
        """
        The YAML text the scenario was read from, as written.

        Returns
        -------
        text : str or None
            The text, or None if the scenario was not read from YAML text
        """
        return self._source_text

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
                scenario = cls.from_yaml_text(file.read(), base_dir=path.parent)
            scenario._source_file = path
            return scenario

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
        scenario = cls.model_validate(data, context={"base_dir": base_dir})
        scenario._source_text = yaml_text
        return scenario

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
            if name == SLEW:
                raise ValueError(
                    f"no attitude may be named '{SLEW}': the attitude row uses it "
                    "while the body turns"
                )
        return attitudes

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

    def _direction_problems(self) -> list[str]:
        """
        Problems with the names: a target named as a built-in direction, an
        attitude with a direction that is neither, an activity's attitude that is
        not defined, and a rise or set of a target that is not defined.

        Returns
        -------
        problems : list of str
            One message for each problem
        """
        problems = [
            f"target '{name}' takes the name of a built-in direction. The built-in "
            f"directions are: {list(DIRECTIONS)}"
            for name in self.targets
            if name in DIRECTIONS
        ]
        known = [*DIRECTIONS, *self.targets]
        for name, attitude in self.attitudes.items():
            problems += [
                f"attitude '{name}': '{direction}' is not a direction. The "
                f"directions are: {known}"
                for direction in attitude.directions
                if direction not in known
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
            f"'{activity.trigger.target}', which targets does not define"
            for number, activity in enumerate(self.activities, start=1)
            if activity.trigger.target is not None
            and activity.trigger.target not in self.targets
        ]
        return problems

    def _park_problems(self) -> list[str]:
        """
        Problems with the articulations: a park mode that no activity has.

        Returns
        -------
        problems : list of str
            One message for each problem
        """
        if self.spacecraft_model is None:
            return []
        modes = sorted({activity.mode for activity in self.activities})
        return [
            f"articulation '{name}': park names the mode '{mode}', which no "
            f"activity has. The activities have: {modes}"
            for name, articulation in self.spacecraft_model.articulations.items()
            for mode in articulation.park
            if mode not in modes
        ]

    @model_validator(mode="after")
    def _check_together(self):
        """
        Checks what spans fields: the step against the duration, the names and
        the directions, and the park modes.

        A duration in orbits is checked against the step only when the run
        starts, once the nodal period is known.
        """
        problems = []
        if isinstance(self.duration, Quantity) and self.step >= self.duration:
            problems.append(
                f"step must be shorter than duration, got '{self.step}' "
                f"and '{self.duration}'"
            )
        problems += self._direction_problems() + self._park_problems()
        if problems:
            raise ValueError("\n".join(problems))
        return self
