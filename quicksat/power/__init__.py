# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The power budget: the power system, the consumption, and the run over the scenario.

The file names are here, so the editor and the commands can name them without the
loaders.
"""

POWER_FILE = "power_system.yaml"
"""The power system file's usual name."""

CONSUMPTION_FILES = {
    "payload": "payload_consumption.csv",
    "platform": "platform_consumption.csv",
}
"""The consumption files' usual names, by the group's name."""
