# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Pydantic and unit parsing helpers.

"""

from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, PlainSerializer, StringConstraints

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


MassQty = non_negative_quantity(u.kg, "mass")
"""Annotated Quantity type restricted to non-negative masses.

Rejects an entry of the wrong dimension, such as '100 W' in a mass column. A plain
float would have accepted it without an error.
"""

LengthQty = non_negative_quantity(u.m, "length")
"""Annotated Quantity type restricted to non-negative lengths."""

AngleQty = non_negative_quantity(u.deg, "angle")
"""Annotated Quantity type for angles.

astropy gives angles a dimension of their own, so this rejects both `500 km` and a
bare `97.4`. An inclination must say whether it is in degrees or radians.
"""


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
