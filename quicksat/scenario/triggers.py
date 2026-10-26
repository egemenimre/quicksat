# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The triggers that end an activity, and the constraints on its illumination.

A trigger is a duration, or an event with an optional offset: a shadow edge, a
latitude crossing, a node, or a target's rise or set. `parse_trigger` reads one,
and `parse_constraint` reads a constraint.

"""

import re
from typing import cast, get_args

from astropy.units import Quantity
from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
)

from quicksat import Q_, u
from quicksat.scenario.names import (
    LATITUDE_CROSSING,
    NODES,
    RISE,
    SET,
    Direction,
    EventName,
    Illumination,
)
from quicksat.utils.intervals import TIME_GRID
from quicksat.utils.parser_helpers import PlainQty


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
        The target that rises or sets, by its name in `gnd_targets` or
        `sat_targets`. Only for a `rise` or a `set`.
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
    - a target's rise or set, such as `Svalbard rise` or `Svalbard set`. For a
      ground target, the satellite passes above or below the target's minimum
      elevation. For a satellite target, the line between the two satellites
      comes to or leaves its minimum clearance above the Earth. The target must
      be one that the scenario names in `gnd_targets` or `sat_targets`.
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
