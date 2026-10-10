# Power generation reference data

Fixture for the power module's first regression test. **No test reads it yet**; the test arrives with the module. It is committed ahead of the code because it cannot be rebuilt in CI: it comes from Orekit, which needs a JVM and the `orekit-data` bundle.

## The scenario

- 510 km sun-synchronous orbit, 10:30 LTAN, inclination 97.4398°.
- SGP4 from the TLE in `scenario.json`, built from those parameters and tuned to a mean altitude of 510.00 km.
- One day from 2026-10-01T00:00:00 UTC at 10 s: 8 640 samples, 15 eclipses.
- Nadir pointing in LVLH: x along track, y is minus the orbit normal, z is nadir. Orekit's `LOFType.LVLH_CCSDS` is the same frame.
- Six 1 m² faces, with normals along ±velocity, ±orbit normal and ±nadir.

## Files

| File | Contents |
|---|---|
| `scenario.json` | Inputs, derived orbit values, the whole-orbit window, expected results, and the agreement the astropy prototype reached |
| `reference_orekit.npz` | Per sample, from Orekit: `cos` (6×N, face order as in `scenario.json`), `lit`, `sun_body` (the sun's unit vector in body axes, 3×N). Also `whole` (the whole-orbit mask) and `flux` |
| `eclipse_orekit.json` | Entry and exit of every eclipse from Orekit's `EclipseDetector`, in seconds from the epoch, located to 1 µs. Five shadow models: spherical Earth with a point sun, and umbra and penumbra on both a sphere and the WGS84 ellipsoid |

Produced on 2026-09-30 with Orekit 13.1 through orekit_jpype 13.1.8.0. Orekit did its own SGP4, TEME → GCRF transform, sun ephemeris, attitude and eclipse detection, so the data is independent of astropy. The one exception is `flux`, which is L_sun / (4π d²) with d from astropy's `get_sun`: the reference tests geometry, not flux.

## What an implementation should reach

The astropy prototype reached these; the power module should too.

| Quantity | Prototype | Tolerance |
|---|---|---|
| Per-sample cosine, every face | 7.9e-5 | 2e-4 |
| Sun direction in body axes | 20.5 arcsec | 30 arcsec |
| Lit flag, cylindrical shadow on the same grid | 0 of 8 640 differ | 0 |
| Whole-orbit mean power per face | 0.024% | 0.1% |
| Eclipse fraction, whole orbits | exact | 1e-4 |
| Mean power against the circular-orbit closed forms in `scenario.json` | 0.43% | 1% |
| Eclipse entry and exit against `sphere_point_sun` | 0.081 s | 0.15 s |
| Eclipse duration against `sphere_point_sun` | 0.059 s | 0.10 s |
| Eclipse edges inside the spherical penumbra | all 30 | all |

These offsets have measured causes:

- **20.5 arcsec in sun direction:** annual aberration. astropy's `get_sun` is the apparent sun, Orekit's the geometric one. This is also where the 7.9e-5 of cosine comes from.
- **Eclipse edges:** a symmetric 0.041 s per edge, because a point sun's shadow widens behind the Earth (R_E/D, 111 m at the edges) while a cylinder's does not; plus about 0.05 s of common shift from the same aberration.

Two things to hold to when the test is written:

- **Average over whole orbits.** Use the `whole` mask, 14 orbits. Averaging over the full day skews per-face means by up to 3.4%.
- **Pick the reference that matches the shadow model.** `sphere_point_sun` is the counterpart of a cylindrical shadow. A conical or oblate model should be compared with the matching umbra and penumbra entries instead, and its lit flags will then differ from `reference_orekit.npz` at the edges.
