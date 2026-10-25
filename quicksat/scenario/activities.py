# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The activities of a scenario, and their modes.

Each activity has a title, a trigger that ends it, an attitude, the payload's
and the platform's modes, and an optional constraint on the illumination. It is
written as a list, or as a mapping with the same fields named.

"""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
)

from quicksat.scenario.names import (
    GROUPS,
    IN_SLEW,
    MODE_KEYS,
    PREV_ACTIVITY,
    RESERVED_NAMES,
    THIS_ACTIVITY,
    Illumination,
)
from quicksat.scenario.triggers import Trigger, parse_constraint, parse_trigger
from quicksat.utils.parser_helpers import (
    COMMENTS,
    Commented,
)


class Modes(BaseModel):
    """
    An activity's two modes, the payload's and the platform's, and the payload's
    mode in the slew into the activity.

    Each mode names a column of its consumption file. The two are independent:
    an imaging activity sets the payload to its imaging mode, and the platform
    to the mode that supports it, such as one with the solar wings parked.

    Parameters
    ----------
    payload : str
        The payload's mode. Any name that is not empty, except `slew` and
        `unplanned`.
    platform : str
        The platform's mode. Any name that is not empty, except `slew`, which
        the run gives the platform while the body turns, and `unplanned`.
    payload_mode_in_slew : str, optional
        The payload's mode in the slew into this activity. `prev_activity`,
        the default, keeps the mode of the activity before, so that a data
        transfer can carry on through the turn. `this_activity` takes this
        activity's mode for the whole slew, so that the payload can prepare for
        it. Without a slew into the activity, it has no effect.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload: str
    platform: str
    payload_mode_in_slew: Literal["prev_activity", "this_activity"] = PREV_ACTIVITY

    def __getitem__(self, group: str) -> str:
        """The mode of one group, `payload` or `platform`."""
        return getattr(self, group)


def parse_modes(value) -> Modes:
    """
    Read an activity's modes, written `{payload_mode: imaging, platform_mode:
    imaging}`, with an optional `payload_mode_in_slew`.

    Parameters
    ----------
    value : dict
        The payload's mode and the platform's, and optionally the payload's
        mode in the slew into the activity

    Returns
    -------
    modes : Modes
        The two modes, stripped, and the payload's mode in the slew

    Raises
    ------
    ValueError
        If it is not a mapping of the two and the optional key, a mode is not
        text, is empty or takes a reserved name, or `payload_mode_in_slew` is
        neither of its two values
    """
    example = "{payload_mode: imaging, platform_mode: imaging}"
    if not isinstance(value, dict):
        raise ValueError(
            f"the mode must give the payload's and the platform's, written "
            f"{example}. Got {value!r}"
        )
    keys = [str(key) for key in value]
    required = list(MODE_KEYS.values())
    if sorted(set(keys) - {IN_SLEW}) != sorted(required):
        raise ValueError(
            f"the mode takes the keys {required} and an optional {IN_SLEW}, "
            f"written {example}. Got {keys}"
        )
    in_slew = value.get(IN_SLEW, PREV_ACTIVITY)
    if in_slew not in (PREV_ACTIVITY, THIS_ACTIVITY):
        raise ValueError(
            f"{IN_SLEW} must be {PREV_ACTIVITY} or {THIS_ACTIVITY}, got {in_slew!r}"
        )
    modes = {IN_SLEW: in_slew}
    for group in GROUPS:
        mode = value[MODE_KEYS[group]]
        if not isinstance(mode, str) or not mode.strip():
            raise ValueError(
                f"the {group}'s mode must be text that is not empty, got {mode!r}"
            )
        mode = mode.strip()
        if mode in RESERVED_NAMES:
            raise ValueError(f"no mode may be named '{mode}': {RESERVED_NAMES[mode]}")
        modes[group] = mode
    return Modes(**modes)


class Activity(Commented):
    """
    One activity: what it is for, what ends it, how the satellite points, and
    what it does.

    Parameters
    ----------
    title : str
        A short name for what the activity is for, such as `imaging 45 deg lat`.
        Any text that is not empty. The tables, the Gantt chart, the warnings and
        the viewer name the activity by it.
    trigger : Trigger
        What ends the activity
    attitude : str
        The name of the attitude, which must be one of the scenario's attitudes
    mode : Modes
        The payload's mode and the platform's, and the payload's mode in the
        slew into the activity
    constraint : str, optional
        The illumination the activity expects: `sunlit`, `penumbra`, `umbra`,
        or `eclipse` for either of the last two
    comments : str, optional
        Your own notes on this block. quicksat keeps them and does not read them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    title: str
    trigger: Trigger
    attitude: str
    mode: Modes
    constraint: Illumination | None = None

    @classmethod
    def from_fields(cls, fields) -> "Activity":
        """
        Build an activity from its list of strings, as written in the file.

        Parameters
        ----------
        fields : list
            The title, the trigger, the attitude, the modes as a mapping and an
            optional constraint

        Returns
        -------
        activity : Activity
            The checked activity

        Raises
        ------
        ValueError
            If the list has the wrong length or a field is not valid
        """
        if not isinstance(fields, (list, tuple)) or len(fields) not in (4, 5):
            raise ValueError(
                "an activity is a list of four or five items: the title, the "
                "trigger, the attitude, the modes and an optional constraint. Got "
                f"{fields!r}"
            )
        names = ("title", "attitude")
        for name, value in zip(names, (fields[0], fields[2]), strict=True):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"the {name} must be text that is not empty, got {value!r}"
                )
        return cls(
            title=fields[0].strip(),
            trigger=parse_trigger(fields[1]),
            attitude=fields[2].strip(),
            mode=parse_modes(fields[3]),
            constraint=parse_constraint(fields[4]) if len(fields) == 5 else None,
        )

    @classmethod
    def from_mapping(cls, fields: dict) -> "Activity":
        """
        Build an activity from its map form, which names each field.

        Parameters
        ----------
        fields : dict
            `title`, `end` (the trigger), `attitude` and `mode`, and optionally
            `constraint` and `comments`

        Returns
        -------
        activity : Activity
            The checked activity

        Raises
        ------
        ValueError
            If a field is missing, unknown or not valid
        """
        required = ("title", "end", "attitude", "mode")
        known = (*required, "constraint", COMMENTS)
        unknown = [str(key) for key in fields if key not in known]
        if unknown:
            raise ValueError(
                f"an activity in the map form takes the keys {list(known)}, got "
                f"{unknown}"
            )
        missing = [key for key in required if key not in fields]
        if missing:
            raise ValueError(f"an activity in the map form needs {missing}")
        listed = [fields[key] for key in required]
        if fields.get("constraint") is not None:
            listed.append(fields["constraint"])
        activity = cls.from_fields(listed)
        comments = fields.get(COMMENTS)
        if comments is not None and not isinstance(comments, str):
            raise ValueError(f"comments must be text, got {comments!r}")
        return activity.model_copy(update={COMMENTS: comments})
