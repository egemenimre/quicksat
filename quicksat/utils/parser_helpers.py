# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Pydantic and unit parsing helpers.

"""

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    PlainSerializer,
    StringConstraints,
)

from quicksat import Q_, u


def _parse_quantity(v):
    """
    Pydantic BeforeValidator for Quantity objects.

    Parameters
    ----------
    v : str or Quantity
        Text such as "100 kg", or an already-parsed Quantity

    Returns
    -------
    quantity : Quantity
        The parsed quantity

    Raises
    ------
    ValueError
        If the text is not a number followed by a unit. astropy raises a
        `TypeError` when the text does not start with a number, which Pydantic
        would not report as a validation error
    """
    if isinstance(v, u.Quantity):
        return v
    try:
        return Q_(str(v).replace("_", ""))
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


def _serialize_quantity(v) -> str:
    """
    Pydantic PlainSerializer for Quantity objects.

    Parameters
    ----------
    v : Quantity
        The quantity to serialise

    Returns
    -------
    text : str
        The quantity as text, value and unit
    """
    return str(v)


def non_negative_quantity(unit, label: str):
    """
    Builds an Annotated Quantity type for one dimension, with non-negative values.

    Parameters
    ----------
    unit : Unit
        Any unit of the required dimension, such as `u.kg` for a mass. The value
        must be convertible to it
    label : str
        Name of the quantity, used in the error messages

    Returns
    -------
    annotated : type
        A type usable as a Pydantic field annotation
    """

    def _validate(v):
        if not v.unit.is_equivalent(unit):
            raise ValueError(f"Value must have {label} dimensions, got '{v}'")
        if v < 0:
            raise ValueError(f"{label.capitalize()} must not be negative, got '{v}'")
        return v

    return Annotated[
        u.Quantity,
        BeforeValidator(_parse_quantity),
        AfterValidator(_validate),
        PlainSerializer(_serialize_quantity, return_type=str),
    ]


def signed_quantity(unit, label: str):
    """
    Builds an Annotated Quantity type for one dimension, with values of either sign.

    Parameters
    ----------
    unit : Unit
        Any unit of the required dimension, such as `u.deg` for an angle. The value
        must be convertible to it
    label : str
        Name of the quantity, used in the error messages

    Returns
    -------
    annotated : type
        A type usable as a Pydantic field annotation
    """

    def _validate(v):
        if not v.unit.is_equivalent(unit):
            raise ValueError(f"Value must have {label} dimensions, got '{v}'")
        return v

    return Annotated[
        u.Quantity,
        BeforeValidator(_parse_quantity),
        AfterValidator(_validate),
        PlainSerializer(_serialize_quantity, return_type=str),
    ]


MassQty = non_negative_quantity(u.kg, "mass")
"""Annotated Quantity type restricted to non-negative masses.

Rejects an entry of the wrong dimension, such as '100 W' in a mass column. A plain
float would have accepted it without an error.
"""

LengthQty = non_negative_quantity(u.m, "length")
"""Annotated Quantity type restricted to non-negative lengths."""

PowerQty = non_negative_quantity(u.W, "power")
"""Annotated Quantity type restricted to non-negative powers, such as `10 W`."""

EnergyQty = non_negative_quantity(u.W * u.h, "energy")
"""Annotated Quantity type restricted to non-negative energies, such as `1024 W h`.
astropy does not read `Wh`, so watt-hours are written with a space."""

AreaQty = non_negative_quantity(u.m**2, "area")
"""Annotated Quantity type restricted to non-negative areas, such as `0.2 m2`."""

AngleQty = non_negative_quantity(u.deg, "angle")
"""Annotated Quantity type for angles.

astropy gives angles a dimension of their own, so this rejects both `500 km` and a
bare `97.4`. An inclination must say whether it is in degrees or radians.
"""

SignedAngleQty = signed_quantity(u.deg, "angle")
"""Annotated Quantity type for angles of either sign, such as `-90 deg`."""

SignedLengthQty = signed_quantity(u.m, "length")
"""Annotated Quantity type for lengths of either sign, such as an altitude below
the ellipsoid."""


PlainQty = Annotated[
    u.Quantity,
    BeforeValidator(_parse_quantity),
    PlainSerializer(_serialize_quantity, return_type=str),
]
"""Annotated Quantity type that is parsed but not dimension-checked.

For a column whose dimension depends on another field, where the check has to be
a model validator rather than a field one.
"""

DataRateQty = non_negative_quantity(u.bit / u.s, "data rate")
"""Annotated Quantity type for data rates.

astropy treats the bit as a unit of its own, so a data rate is information over
time. This rejects `800 MHz` as well as `500 km`. `800 Mbps` does not parse at all,
so write `800 Mbit/s`.
"""

TimeQty = non_negative_quantity(u.s, "time")
"""Annotated Quantity type restricted to non-negative durations."""

AngularRateQty = non_negative_quantity(u.deg / u.s, "angular rate")
"""Annotated Quantity type for non-negative angular rates, such as `0.7 deg/s`."""

AngularAccelerationQty = non_negative_quantity(u.deg / u.s**2, "angular acceleration")
"""Annotated Quantity type for non-negative angular accelerations, such as
`0.08 deg/s2`."""

FractionQty = non_negative_quantity(u.dimensionless_unscaled, "fraction")
"""Annotated Quantity type for dimensionless fractions, written as percentages.

astropy reads `5 %` as 5 percent, which converts to 0.05 of one, so a duty cycle
can be entered either way.
"""

NoSpaceStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\S+$")]
"""String field that must not contain whitespace, used for the grouping axes."""

MomentumQty = non_negative_quantity(u.N * u.m * u.s, "angular momentum")
"""Annotated Quantity type for angular momentum, as a wheel stores it (`4 N*m*s`)."""

TorqueQty = non_negative_quantity(u.N * u.m, "torque")
"""Annotated Quantity type for torque.

Torque and energy share a dimension, so this rejects `4 N*m*s` but cannot tell
`0.2 N*m` from `0.2 J`.
"""

InertiaQty = non_negative_quantity(u.kg * u.m**2, "moment of inertia")
"""Annotated Quantity type for a moment of inertia (`264.7 kg*m**2`)."""


COMMENTS = "comments"
"""The key of the user's own notes, which every block of an input file may have.
quicksat keeps them and does not read them. No named item may take this name."""


class Commented(BaseModel):
    """
    A block of an input file that may hold the user's own notes.

    The notes go in `comments`, so that every YAML reader keeps them, the editor
    included. A `#` comment is lost when the editor saves the file.

    Parameters
    ----------
    comments : str, optional
        The user's notes on the block. quicksat does not read them.
    """

    comments: str | None = None


def without_comments(value):
    """
    Pydantic BeforeValidator for a mapping of named items, such as the attitudes.

    The mapping may hold the user's notes on the whole section under `comments`.
    They are taken out before the items are read, so no item may take that name.

    Parameters
    ----------
    value
        The mapping as the file gives it, or anything else, which is passed on

    Returns
    -------
    value
        The mapping without its `comments` key

    Raises
    ------
    ValueError
        If `comments` holds anything but text, such as an item that took the name
    """
    if not isinstance(value, dict) or COMMENTS not in value:
        return value
    if not (value[COMMENTS] is None or isinstance(value[COMMENTS], str)):
        raise ValueError(
            f"'{COMMENTS}' holds the notes on the whole section, so no item may "
            "take that name"
        )
    return {name: item for name, item in value.items() if name != COMMENTS}
