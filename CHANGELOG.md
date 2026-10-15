# Changelog

All notable changes to quicksat are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-15

Initial release.

### Getting started

- `pip install quicksat`, then `python -m quicksat init FOLDER` copies the samples from GitHub into a folder: their data, their notebooks, and the viewers and editor pages written from them.

### Sizing

- The mass budget, with equipment margins, a system margin and totals by location.
- The data and downlink budget.
- The delta-V budget, with the propellant mass from the mass budget.
- The attitude agility budget: rest-to-rest slews about each axis.
- One shared mission file, `mission.yaml`, with the reference orbit and the design life.

### Scenario

- The orbit from a TLE, an OMM, a sun-synchronous orbit definition, or a trajectory file in ECSV or CCSDS OEM.
- The umbra and the penumbra on the WGS84 ellipsoid, and the light fraction.
- A timeline of activities, with triggers on durations, shadow edges, latitude crossings, nodes and a ground target's rise and set.
- User-named attitudes, with ground targets and yaw steering, and the slews between them.
- A check of each activity's constraint, and warnings where the body turns faster than the slew limits.
- Articulations: parts of the 3D model, such as solar wings, that turn to point at a direction.
- The attitude, and each articulation's angle, written as ECSV files.
- `python -m quicksat.scenario FOLDER OUTPUT` runs a scenario folder from the command line.

### Power

- The generation from the solar panels of the 3D model, with self-shadowing.
- The consumption, with a power for each equipment in each mode.
- The power budget, with the battery and the power conditioning.
- `python -m quicksat.power FOLDER OUTPUT` runs a power folder from the command line.

### Viewer

- A page that shows a scenario or power run, with no Python: the orbit, the body and its 3D model in 3D, the ground track, the timeline, the activities, the attitude, and the net power and the battery.

### Editors

- The Scenario Editor, for the scenario and power files, and the Sizing Editor, for the sizing files. Each is a page with step-by-step setup and tabs by theme.
- Each block of a file holds the user's notes in a `comments` field, which survive edits and saves.
- The pages open a folder or a single file, and save as a zip or one file at a time.
- A ground target search, through OpenStreetMap's Nominatim.
- `python -m quicksat.editor serve FOLDER OUTPUT` serves the Scenario Editor on this computer, with a button that runs the page's files and writes the viewer.

[Unreleased]: https://github.com/egemenimre/quicksat/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/egemenimre/quicksat/tree/v0.1.0
