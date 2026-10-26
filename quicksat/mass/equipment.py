# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Equipment items making up the mass budget.

"""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from quicksat.utils.parser_helpers import MassQty, NoSpaceStr


class MassClass(str, Enum):
    """How an equipment item behaves in the mass budget cases."""

    EQUIPMENT = "equipment"
    """Ordinary hardware. Carries margins and is counted in every case."""

    PROPELLANT = "propellant"
    """Consumable. Scaled by the `propellant` percentage, and never takes a margin."""


def _default_mass_class(v):
    """Reads a blank mass class as `equipment`."""
    if v is None:
        return MassClass.EQUIPMENT
    if isinstance(v, str):
        text = v.strip().lower()
        return MassClass.EQUIPMENT if not text else text
    return v


class Equipment(BaseModel):
    """A single line item of the mass budget, validated as it is read."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    equipment_id: NoSpaceStr
    """Short identifier, no whitespace (e.g. `star_tracker`)."""

    equipment_name: str
    """Full name, free text (e.g. "Jena Astro HP")."""

    location: NoSpaceStr
    """Where the item sits. It sets the harness and the system margin, and what survives
    separation."""

    responsibility: NoSpaceStr
    """Who is responsible for the item. Reporting axis only."""

    subsystem: NoSpaceStr
    """Subsystem the item belongs to (e.g. `ADCS`). Reporting axis only."""

    unit_mass: MassQty
    """Mass of a single unit, entered with its unit (e.g. "100 kg")."""

    eqpt_margin: Annotated[float, Field(ge=0)]
    """Per-item mass contingency, as a percentage (`20` means 20%)."""

    number_of_units: Annotated[int, Field(ge=0)]
    """Number of units flown. May be zero to keep an item in the file without mass."""

    mass_class: Annotated[MassClass, BeforeValidator(_default_mass_class)] = (
        MassClass.EQUIPMENT
    )
    """Behaviour in the mass cases. Blank defaults to `equipment`."""

    comments: str = ""
    """Free text notes."""
