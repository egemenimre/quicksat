# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
A budget's checks: each compares a figure of the design with the limit it must meet.

The notebooks and the Sizing Editor both read this code, so they give the same verdicts.

"""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pandas.io.formats.style import Styler

from quicksat import Q_, u


@dataclass(frozen=True)
class Check:
    """
    One figure of the design against the limit it must meet.

    Parameters
    ----------
    name : str
        A short name, such as the requirement's, `roll_40`, or `propellant`
    description : str
        What is checked, as a sentence
    design : Quantity
        What the design gives
    limit : Quantity
        What the design must reach, or must not pass
    at_most : bool
        Whether the design must stay at or below the limit, as a slew's time must
    """

    name: str
    description: str
    design: u.Quantity
    limit: u.Quantity
    at_most: bool = False

    @property
    def spare(self):
        """What the design has to spare, in its unit, negative when it falls short."""
        spare = self.limit - self.design if self.at_most else self.design - self.limit
        return Q_(spare, self.design.unit)

    @property
    def margin(self):
        """
        The spare as a share of what the design needs or uses: 0.12 is 12 %, and a need
        of zero gives infinity.
        """
        have, need = (
            (self.limit, self.design) if self.at_most else (self.design, self.limit)
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            return Q_(have / need - 1, u.dimensionless_unscaled)

    @property
    def passes(self) -> bool:
        """Whether the design meets the limit."""
        return bool(self.spare.value >= 0)


def _text(quantity, sign: bool = False) -> str:
    """A quantity as text, with two decimals, and a data volume in GB or TB."""
    text = f"{quantity:+.2f}" if sign else f"{quantity:.2f}"
    return text.replace("byte", "B")


def tabulate(checks: Iterable[Check]) -> Styler:
    """
    The checks as a table, one row each.

    Parameters
    ----------
    checks : iterable of Check
        The checks, such as a budget's `checks()`

    Returns
    -------
    table : Styler
        The name, what is checked, the design, the limit, the spare, the margin and the
        verdict, `PASS` or `FAILS`
    """
    rows = [
        {
            "check": check.name,
            "description": check.description,
            "design": _text(check.design),
            "limit": f"{'≤' if check.at_most else '≥'} {_text(check.limit)}",
            "spare": _text(check.spare, sign=True),
            "margin": f"{check.margin.to_value('percent'):+.1f} %",
            "verdict": "PASS" if check.passes else "FAILS",
        }
        for check in checks
    ]
    columns = ["check", "description", "design", "limit", "spare", "margin", "verdict"]
    return pd.DataFrame(rows, columns=columns).style.hide(axis="index")
