"""Settings for the whole test suite.

astropy downloads the IERS table of the Earth's orientation again when a run
needs predicted values, and the table's predictions started more than 30 days
ago. While the IERS server is late with a new table, that happens in every new
process, for 10 to 20 s each. The tests run on fixed dates, so they turn the age
check off and use the table in astropy's cache. Without a cached table, astropy
still downloads it once.
"""

from astropy.utils import iers

iers.conf.auto_max_age = None  # noqa: V101
