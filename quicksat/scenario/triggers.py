# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The triggers that end an activity, and the constraints on its illumination.

`docs/scenario/scenario_ref.ipynb`, under "The triggers", lists the forms.

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
    What ends an activity: a duration, or an event with an optional offset. Build one
    with `parse_trigger`.

    Parameters
    ----------
    text : str
        The trigger as written, with its spaces tidied
    duration : Quantity, optional
        The activity's length, for a duration trigger
    event : str, optional
        The event's kind, such as `eclipse entry`, `latitude crossing` or `rise`. A node
        is a crossing of 0 degrees
    latitude : Quantity, optional
        The geodetic latitude crossed, for a latitude crossing
    direction : str, optional
        `ascending`, `descending`, or None for either, for a latitude crossing
    target : str, optional
        The target that rises or sets
    offset : Quantity, optional
        Time added to the event, negative to end before it
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
        """Checks the fields given suit a duration or an event."""
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
        The event without its offset, as a lookup key: its kind, then its latitude and
        direction or its target. None for a duration.
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
"""A target's rise or set, such as `Svalbard rise`, with an optional offset. The name
keeps its case and spaces."""


def _trigger_forms() -> str:
    """The accepted forms of a trigger, in one sentence, for the error."""
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
    A latitude trigger's latitude in degrees, refusing one that is not an angle from -90
    to 90.
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
    An event trigger's offset, negative for `-`, refusing one that is not a time with a
    unit.
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
    """An event trigger from tidied text, or None if the text is not one."""
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

    The forms are a positive duration, such as `20 min`, or an event: a shadow edge,
    such as `eclipse entry`, a latitude crossing, such as `latitude 30 deg ascending`, a
    node, or a target's rise or set, such as `Svalbard rise`. An event may take an
    offset, such as `eclipse entry + 2 min`. The words may be in any case, except a
    target's name.

    Parameters
    ----------
    text : str
        The trigger as written

    Returns
    -------
    trigger : Trigger
        The trigger

    Raises
    ------
    ValueError
        If the text is none of the forms, which the message lists
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
        `sunlit`, `penumbra`, `umbra`, or `eclipse`

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
