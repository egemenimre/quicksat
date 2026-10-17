# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
Write `relays.tle`, the relay constellation of the scenario reference notebook.

Ten relays, RELAY-01 to RELAY-10, in a Walker star of two planes of five, at
1200 km and 87.9 deg, as Telesat's polar shell. The two planes' nodes are 90 deg
apart, which spreads two planes over the 180 deg of a star. The relays of a plane
are 72 deg apart, and the second plane's are 36 deg on from the first's. Seen
from a 510 km sun-synchronous orbit, at least one relay is always in view, with
100 km of clearance.

The orbits are circular, with no drag, as `quicksat.orbit.sso` builds its
orbit. The altitude is averaged over one orbit. The epoch is the reference
scenario's start, so the file is never stale for it. The elements are made up:
no such satellites fly.

Run it from the repository's root, after a change:

    python -m docs.scenario.data.make_relays

"""

from pathlib import Path

import numpy as np
from astropy.time import Time
from sgp4.api import WGS72, Satrec

from quicksat import MU_EARTH, Q_, R_EARTH, u
from quicksat.orbit.tle import Tle

EPOCH = Time("2026-10-01T00:00:00", scale="utc")
"""The epoch: the reference scenario's start."""

ALTITUDE = Q_(1200, "km")
"""The altitude, averaged over one orbit."""

INCLINATION = Q_(87.9, "deg")
"""The inclination of both planes."""

PLANES, PER_PLANE = 2, 5
"""Two planes of five relays."""

FIRST_NUMBER = 90001
"""The catalogue number of RELAY-01. The others follow it."""

_SGP4_EPOCH_ZERO = 2433281.5
"""1949-12-31 00:00 UTC as a Julian date, the zero of SGP4's epoch."""


def relay(number: int, node: float, anomaly: float, mean_motion: float) -> Satrec:
    """A circular orbit with no drag, at a node and a mean anomaly in radians."""
    satrec = Satrec()
    satrec.sgp4init(
        WGS72, "i", number, float((EPOCH.jd1 - _SGP4_EPOCH_ZERO) + EPOCH.jd2),
        0.0, 0.0, 0.0,  # B*, and the first and second derivatives of the mean motion
        0.0, 0.0, INCLINATION.to_value(u.rad), anomaly, mean_motion, node,
    )  # fmt: skip
    return satrec


def mean_radius(satrec: Satrec) -> float:
    """The distance from the centre of the Earth, averaged over one orbit, in km."""
    minutes = np.linspace(0, 2 * np.pi / satrec.no_kozai, 360, endpoint=False)
    _, position, _ = satrec.sgp4_array(
        np.full(minutes.size, satrec.jdsatepoch), satrec.jdsatepochF + minutes / 1440
    )
    return float(np.linalg.norm(position, axis=1).mean())


def main() -> None:
    """Fit the mean motion to the altitude, and write the ten relays."""
    radius = (R_EARTH + ALTITUDE).to_value(u.km)
    # Kepler's law for the first guess, then SGP4's own averaged radius
    mean_motion = float(np.sqrt(MU_EARTH / (R_EARTH + ALTITUDE) ** 3).to_value("1/min"))
    for _ in range(10):
        found = mean_radius(relay(FIRST_NUMBER, 0.0, 0.0, mean_motion))
        mean_motion *= (found / radius) ** 1.5
    lines = []
    for plane in range(PLANES):
        for slot in range(PER_PLANE):
            index = plane * PER_PLANE + slot
            node = np.radians(90.0 * plane)
            anomaly = np.radians(72.0 * slot + 36.0 * plane)
            satrec = relay(FIRST_NUMBER + index, node, anomaly, mean_motion)
            lines += [f"RELAY-{index + 1:02d}", *Tle(None, satrec).lines]
    path = Path(__file__).with_name("relays.tle")
    path.write_text("\n".join(lines) + "\n")
    altitude = mean_radius(satrec) - R_EARTH.to_value(u.km)
    print(f"{path}: {len(lines) // 3} relays, at {altitude:.1f} km")


if __name__ == "__main__":
    main()
