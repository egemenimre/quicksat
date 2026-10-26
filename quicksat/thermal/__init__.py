# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The payload's heat account over a scenario run, which sizes its radiators and heaters.

Thermal is a sub-domain of power: its file sits in the power folder, and it reads the
payload's consumption and the power system. `decisions.md` 26 says why. The file name is
here, so the editor and the commands can name it without the loader.
"""

THERMAL_FILE = "payload_thermal.yaml"
"""The payload's thermal file's usual name. The file is optional."""
