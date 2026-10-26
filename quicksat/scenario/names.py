# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The names that the scenario file and the run share, apart from the loaders, so a module
can use them without importing those.

"""

from typing import Literal

Axis = Literal["+x", "-x", "+y", "-y", "+z", "-z"]
"""A body axis, with its sign: the axis the attitude points along."""

Illumination = Literal["sunlit", "penumbra", "umbra", "eclipse"]
"""The constraints an activity may have: `sunlit`, `penumbra`, `umbra`, and `eclipse`
for either of the last two."""

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
"""Direction: the velocity relative to the turning Earth, for yaw steering."""

DIRECTIONS = (NADIR, SUN, ORBIT_NORMAL, VELOCITY, GROUND_VELOCITY)
"""The built-in directions. Each target is a direction too."""

FALLBACKS = (ORBIT_NORMAL, NADIR, VELOCITY)
"""The default fallback is the first of these that the attitude does not use."""

SLEW = "slew"
"""The attitude's and the platform's mode while the body turns or settles. No attitude
or mode may take it."""

UNPLANNED = "unplanned"
"""The attitude and the modes after the last activity, in a run of the list once. No
attitude or mode may take it."""

PAYLOAD = "payload"


PLATFORM = "platform"


GROUPS = (PAYLOAD, PLATFORM)
"""The two parts of the spacecraft that each have a mode: the payload, and the platform
that carries it."""

MODE_KEYS = {group: f"{group}_mode" for group in GROUPS}
"""The keys of an activity's modes in the file, by group."""

IN_SLEW = "payload_mode_in_slew"
"""The key of the payload's mode in the slew into an activity."""

PREV_ACTIVITY = "prev_activity"


THIS_ACTIVITY = "this_activity"
"""The two values of `payload_mode_in_slew`: the mode of the activity before the slew,
or this activity's."""

RESERVED_NAMES = {
    SLEW: "the run gives the attitude and the platform's mode that name while the "
    "body turns",
    UNPLANNED: "the run gives the attitude and mode rows that name after the last "
    "activity",
}
"""The names that no attitude and no mode may take, with the reason."""
