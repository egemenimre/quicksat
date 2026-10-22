# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
A budget's checks: each one compares a figure of the design with the limit it
must meet.

A budget with something to meet gives its checks with `checks()`. The notebooks
show them, and so does the sizing editor, beside the budget tables. Both read
this code, so the two cannot give different verdicts.

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
        A short name: the requirement's own, such as `roll_40`, or the check's,
        such as `propellant`
    description : str
        What is checked, as a sentence
    design : Quantity
        What the design gives
    limit : Quantity
        What the design must reach, or must not pass
    at_most : bool
        Whether the design must stay at or below the limit, as a slew's time
        must. Otherwise it must reach the limit, as the propellant loaded must.
    """

    name: str
    description: str
    design: u.Quantity
    limit: u.Quantity
    at_most: bool = False

    @property
    def spare(self):
        """
        What the design has to spare. It is negative when the design falls
        short.

        Returns
        -------
        spare : Quantity
            In the design's unit
        """
        spare = self.limit - self.design if self.at_most else self.design - self.limit
        return Q_(spare, self.design.unit)

    @property
    def margin(self):
        """
        The spare, as a share of what the design needs or uses.

        For a limit the design must reach, it is the design over the limit, less
        one. For a limit it must not pass, it is the limit over the design, less
        one, as `AgilityBudget.time_margin` gives. A need of zero, such as no
        orbits without downlink, gives an infinite margin.

        Returns
        -------
        margin : Quantity
            Dimensionless, so 0.12 is a 12% margin
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
    """
    A quantity as text, with two decimals. A data volume is written in GB or TB,
    as the data budget's table writes it, where astropy would print `Gbyte`.
    """
    text = f"{quantity:+.2f}" if sign else f"{quantity:.2f}"
    return text.replace("byte", "B")


def tabulate(checks: Iterable[Check]) -> Styler:
    """
    The checks as a table, one row each, for reading.

    Parameters
    ----------
    checks : iterable of Check
        The checks, such as a budget's `checks()`

    Returns
    -------
    table : Styler
        The name, what is checked, the design, the limit, the spare and the
        margin, as text, and the verdict: `PASS` or `FAILS`. The frame is
        available as `.data`
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
