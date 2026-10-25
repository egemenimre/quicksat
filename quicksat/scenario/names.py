# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The names that the scenario file and the run share: the body axes, the
directions, the events, the illumination, the two groups and their modes, and
the names that no attitude and no mode may take.

They sit apart from the scenario's loaders, so that a module can use them
without importing the loaders.

"""

from typing import Literal

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
"""The built-in directions. A target named in `gnd_targets` or `sat_targets` is a
direction too."""

FALLBACKS = (ORBIT_NORMAL, NADIR, VELOCITY)
"""The default fallback is the first of these that the attitude does not use."""

SLEW = "slew"
"""The value of the attitude row and the platform's mode row while the body turns
or settles. No attitude and no mode may take this name."""

UNPLANNED = "unplanned"
"""The value of the attitude and mode rows after the last activity, in a run of
the list once or of an empty list. No attitude and no mode may take this name."""

PAYLOAD = "payload"


PLATFORM = "platform"


GROUPS = (PAYLOAD, PLATFORM)
"""The two parts of the spacecraft that each have a mode at a time: the payload,
and the platform that carries it."""

MODE_KEYS = {group: f"{group}_mode" for group in GROUPS}
"""The keys of an activity's modes in the file, by group."""

IN_SLEW = "payload_mode_in_slew"
"""The key of an activity's modes that says which mode the payload is in during
the slew into the activity."""

PREV_ACTIVITY = "prev_activity"


THIS_ACTIVITY = "this_activity"
"""The two values of `payload_mode_in_slew`. The payload keeps the mode of the
activity before the slew, or takes this activity's mode for the whole slew."""

RESERVED_NAMES = {
    SLEW: "the run gives the attitude and the platform's mode that name while the "
    "body turns",
    UNPLANNED: "the run gives the attitude and mode rows that name after the last "
    "activity",
}
"""The names that no attitude and no mode may take, with the reason."""
