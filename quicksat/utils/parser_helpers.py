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


def _validate_mass(v):
    """
    Pydantic AfterValidator that requires a non-negative mass Quantity.

    Parameters
    ----------
    v : Quantity
        The parsed quantity to check

    Returns
    -------
    quantity : Quantity
        The same quantity, unchanged

    Raises
    ------
    ValueError
        If the quantity is not a mass, or is negative
    """
    if not v.check("[mass]"):
        raise ValueError(f"Value must have mass dimensions, got '{v}'")
    if v.magnitude < 0:
        raise ValueError(f"Mass must not be negative, got '{v}'")
    return v


MassQty = Annotated[
    u.Quantity,
    BeforeValidator(_parse_quantity),
    AfterValidator(_validate_mass),
    PlainSerializer(_serialize_quantity, return_type=str),
]
"""Annotated Quantity type restricted to non-negative masses.

Rejects a dimensionally wrong entry such as '100 W' in a mass column, which a
plain float would have silently accepted.
"""

NoSpaceStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\S+$")]
"""String field that must not contain whitespace, used for the grouping axes."""
