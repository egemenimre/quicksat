# Changelog

All notable changes to quicksat are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A sun-synchronous orbit takes the local time of the descending node, `ltdn`, in place of `ltan`. The two are 12 h apart. The Scenario Editor's Orbit step has a choice of node, and switching it keeps the orbit.
- Both editors open a folder, or its files, dropped onto the page, and a file dropped onto its tab's bar. The buttons still open the file picker.
- `python -m quicksat init` prints where the input files and everything else went, and the steps to start the editor's server. The README walks through the server step by step.
- The viewer holds every input file of its run. Its Inputs tab now shows the orbit's file, for a TLE, an OMM or a trajectory file, and the power consumption file. `scenario.js` is version 6, and `power.js` version 2.
- Other satellites as targets, in the scenario file's new `sat_targets` block, such as the relays of a constellation. Each takes its orbit from a TLE, OMM or trajectory file. Attitudes and articulations can point at one, and `RELAY-01 rise` and `RELAY-01 set` end activities when it comes into view and goes out of it. A satellite is in view while the line between the two keeps `min_clearance` above the Earth, 100 km by default.
- A TLE or OMM file may hold a group of satellites, as CelesTrak and Space-Track give them. A satellite target takes the one of its own name, or the one that `object` names. `read_tle_sets` and `read_omm_sets` read every element set in a file, and `read_tle_file` and `read_omm_file` take a `satellite`.
- `run.in_view` gives when each target, ground or satellite, is in view, and `run.passes` lists the passes. The run's report gives each target's passes and its time in view.
- The viewer draws the targets on the globe, in the body view and on the map, with lines to the targets in view and to the ones the spacecraft points at. Ground targets are pink, and satellite targets lime. Its new Targets tab shows each target's passes, when the attitude or a part points at it, its range now and where its orbit came from. `scenario.js` is version 7.
- The Scenario Editor has a Targets tab, and a Satellite targets step. It adds targets from a file, and lists a group's satellites to choose from. The page holds each file, and saves and runs it with the scenario.
- The scenario reference notebook has a section on satellite targets, with ten made-up relays at 1200 km in `docs/scenario/data/relays.tle`. The sample scenario tracks one of them after each eclipse.

### Changed

- The editors' help sits in one file per domain, in `quicksat/editor/help/`: each step's information box, and the `#` help lines that the editor writes into saved files. The text itself is unchanged.
- The scenario file's `targets` block is now `gnd_targets`, for the ground points, beside `sat_targets` for the satellites. A file with `targets` is refused, so rename the key in older files.
- An element set's epoch is checked against both ends of the run, not only its start. Its warning, and a trajectory's near its ends, are now among the run's own warnings, so the viewer and the editor show them.
- The viewer reads `scenario.js` version 7 only. An older one asks for the notebook to be run again.

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
