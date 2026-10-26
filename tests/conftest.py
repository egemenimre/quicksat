"""
Settings for the whole test suite.

The tests run on fixed dates, so they turn astropy's IERS age check off and use the
cached table. Otherwise a late IERS table costs 10 to 20 s of download in every process.
"""

from astropy.utils import iers

iers.conf.auto_max_age = None  # noqa: V101
