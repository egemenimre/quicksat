# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Package for Pydantic and unit parsing helpers.

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
        The parsed quantity, bound to the shared registry
    """
    if isinstance(v, u.Quantity):
        return v
    return Q_(str(v).replace("_", ""))


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
        The quantity as text, magnitude and unit
    """
    return str(v)


def non_negative_quantity(dimension: str, label: str):
    """
    Builds an Annotated Quantity type restricted to one dimension and to non-negative values.

    Parameters
    ----------
    dimension : str
        Dimensionality the value must have, in pint's notation (`"[mass]"`)
    label : str
        Name of the quantity, used in the error messages

    Returns
    -------
    annotated : type
        A type usable as a Pydantic field annotation
    """

    def _validate(v):
        if not v.check(dimension):
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


MassQty = non_negative_quantity("[mass]", "mass")
"""Annotated Quantity type restricted to non-negative masses.

Rejects a dimensionally wrong entry such as '100 W' in a mass column, which a
plain float would have silently accepted.
"""

LengthQty = non_negative_quantity("[length]", "length")
"""Annotated Quantity type restricted to non-negative lengths."""

AngleQty = non_negative_quantity("", "angle")
"""Annotated Quantity type for angles.

pint treats radians as dimensionless, so this checks only that the value carries
no other dimension: it rejects `500 km` but cannot tell `97.4 deg` from a bare
`97.4`.
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

DataRateQty = non_negative_quantity("1/[time]", "data rate")
"""Annotated Quantity type for data rates.

Bits are dimensionless in pint, so a data rate has the dimensionality of a
frequency. This rejects `500 km` but cannot tell `800 Mbit/s` from `800 MHz`.
"""

TimeQty = non_negative_quantity("[time]", "time")
"""Annotated Quantity type restricted to non-negative durations."""

FractionQty = non_negative_quantity("", "fraction")
"""Annotated Quantity type for dimensionless fractions, written as percentages.

pint reads `5 %` as 0.05, so a duty cycle can be entered either way.
"""

NoSpaceStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\S+$")]
"""String field that must not contain whitespace, used for the grouping axes."""
