# quicksat Basic satellite sizing tool
#
# Copyright (C) Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.md for more info.
"""
The payload's heat account over a scenario run, which sizes its radiators and
heaters.

Thermal is a sub-domain of power: it cannot exist without it. Its file sits in the
power folder, and it reads two of power's files: the payload's consumption, for the
dissipation and the heaters, and the power system, for the self-shadowing. Its
command runs the power budget too.

The file name is here, rather than in `config`, so that the editor and the
commands can name the file without importing the loader.
"""

THERMAL_FILE = "payload_thermal.yaml"
"""The payload's thermal file's usual name. The file is optional."""
