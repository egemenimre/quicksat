# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The requirements: what the mission asks of the spacecraft.

A requirement is asked of a spacecraft, and is not a property of one. So the
requirements have a file of their own, `requirements.yaml`, beside the budgets'
files. A budget reads its own section, and checks its figures against it with
`checks()`.

The file and each of its sections are optional. A budget with no requirement
still works out its figures, and gives no check for that requirement.

"""

from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, Field

from quicksat.agility.budget import Axis
from quicksat.utils.parser_helpers import (
    AngleQty,
    Commented,
    TimeQty,
    YamlFile,
    without_comments,
)


class SlewRequirement(Commented):
    """
    A slew the mission needs: an angle about one axis, in a time.

    Parameters
    ----------
    axis : Axis
        The axis the slew is about
    angle : Quantity
        How far the spacecraft turns
    duration : Quantity
        The time the slew may take, settling included
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    axis: Axis
    angle: AngleQty
    duration: TimeQty


class AgilityRequirements(Commented):
    """
    What the mission asks of the agility.

    Parameters
    ----------
    slews : dict of str to SlewRequirement
        The slews the mission needs, keyed by any names you choose. Different
        operations may ask different times of the same spacecraft
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(extra="forbid")

    slews: Annotated[dict[str, SlewRequirement], BeforeValidator(without_comments)]


class DataRequirements(Commented):
    """
    What the mission asks of the data handling.

    Parameters
    ----------
    orbits_without_downlink : float
        The longest run of orbits with no payload data downlink. The mass memory must
        hold the data generated over it
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(extra="forbid")

    orbits_without_downlink: float = Field(ge=0)


class Requirements(YamlFile):
    """
    What the mission asks of the spacecraft, by budget.

    Parameters
    ----------
    agility : AgilityRequirements, optional
        The slews the mission needs
    data : DataRequirements, optional
        The time the mass memory must cover
    comments : str, optional
        The user's notes on the block. quicksat does not read them
    """

    model_config = ConfigDict(extra="forbid")

    # text with no requirement in it gives none
    _EMPTY_ALLOWED = True

    agility: AgilityRequirements | None = None
    data: DataRequirements | None = None
