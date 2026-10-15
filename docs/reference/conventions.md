# Conventions

Rules the code and the notebooks follow.

## Units

**Use numpy, never `math`, on anything that might carry a unit.** numpy's functions understand units. `np.sin` converts an angle in degrees by itself. `np.sqrt` of an area returns a length. `np.exp` of a length raises an error instead of returning a number. `math` fails on a quantity with a unit, and drops the unit from a dimensionless one.

**Write `123 * u.m` in notebooks, and use the constructor in the package.** In a notebook, values should read like arithmetic. In the package, write `Q_(123, "m")`. Use the constructor also for a unit string held in a variable, such as a YAML value or a CSV cell: `Q_(text)`.

**Strip a unit only where a value must be a plain number,** such as a DataFrame cell or a count used as a multiplier. Use `.to_value(unit)`, which names the unit of the number. `.value` returns the number in whatever unit the quantity carries. It is safe only just after that unit was fixed.

**Simplify clashing units with `.decompose()`.** astropy does not cancel different units of the same dimension by itself. `10 * u.km / (10000 * u.m)` is `0.001 km / m`, and its `.value` is 0.001, not 1. `.decompose()` reduces it to base units, giving 1. It simplifies without checking the result. For a ratio that must be dimensionless, `.to(u.dimensionless_unscaled)` also simplifies, and raises an error if the ratio is not dimensionless.

**Dimensionless is `u.dimensionless_unscaled`,** the name astropy's documentation prefers. As a string it is `""`, so `Unit("")` gives the same unit.

**Angles have their own dimension.** astropy does not treat a radian as a pure number. Sometimes a ratio of physical quantities is an angle. Momentum over inertia, for example, comes out in 1/s, which means rad/s. Convert such a ratio with `equivalencies=u.dimensionless_angles()`. Do it only at that conversion, so that an accidental mix anywhere else still raises an error.

**Write data rates in `Mbit/s`, never `Mbps`.** The bit is a unit in astropy. A data rate is bits over time, so a frequency is not a data rate. astropy has no `bps`. `GB` is the decimal gigabyte, and astropy prints it as `Gbyte`.

**Use SI units wherever possible.** Imperial units such as `lb` are not accepted: an input file that uses one is rejected on load.

**Temperatures need `equivalencies=u.temperature()` to convert.** `25 * u.deg_C` is a valid quantity, but it does not convert to kelvin without the equivalency. The equivalency treats every value as an absolute temperature. So 5 °C becomes 278.15 K, even when it meant a difference of 5 K. Work out temperature differences in kelvin.

**Constants come from `astropy.constants`.** That module creates its constants when it is imported, so a static checker cannot see them. The import therefore carries `# pyright: ignore[reportAttributeAccessIssue]`. quicksat's `R_EARTH` and `MU_EARTH` are astropy's defaults, `R_earth` and `GM_earth`. The sun's radius in `quicksat.orbit.geometry` is `R_sun`. astropy.constants has no WGS84 values, so that module writes the ellipsoid's radius and flattening out.

## Tests

**Tolerances carry units.** Use `assert_quantity_allclose` from `astropy.tests.helper`, as in `assert_quantity_allclose(actual, expected, atol=Q_(0.1, "kg"))`. It refuses a bare `atol` unless the quantity is dimensionless. That is deliberate: a tolerance without a unit is the kind of error units exist to catch.

**The viewer's logic is tested in Node.** The checks on the data files and the values between grid steps sit in `quicksat/scenario/templates/viewer_logic.js`, apart from the page's drawing code. The tests in `tests/scenario/js/` load that file as the page does. They run with Node's own test runner, `node --test "tests/**/*.test.js"`, or with `tox -e javascript`, and need no npm packages. CircleCI runs them in its `javascript` job. The drawing code, with three.js and uPlot, has no tests: check it in a browser.

**The editor's comment finder is tested in Node too.** `quicksat/editor/templates/shared/open.js` must find the same `#` comments as `comment_blocks` in Python. Node cannot call Python, so `tests/editor/js/open_cases.json` holds the cases with Python's answers: some awkward layouts and a copy of quicksat's own YAML files. `tests/editor/js/open.test.js` checks the page against them, and `tests/editor/test_open_js.py` checks that they are still Python's. After a change to Python's readers, or to add newer YAML files, write the cases again with `python -m tests.editor.test_open_js`.
