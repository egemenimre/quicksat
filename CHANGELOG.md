# Changelog

All notable changes to quicksat are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The Sizing Editor's Budgets tab has an Export to Excel button. It writes an .xlsx workbook: an overview of the headline figures and the checks, then a sheet for each budget. The mass budget has two sheets, in orbit and on the ground, with comments and without subsystem subtotals. Agility has two, about roll and about pitch, for the selected inertia case with the full set of wheels. Each number is written in full, and shows the decimals that the tab shows. The workbook holds values only, with no formulas. The page writes it, so it needs no server and no Python package.

### Changed

- `budget_results` gives each table row its `values`, the numbers in full beside the text of its `cells`. Each figure has its `number`, and each check its `numbers`. The delta-V table keeps its loss factor column, which the tab hides. The propellant table has a value column and a unit column.
- On the Budgets tab, the margin columns of the mass budget's tables by location and by subsystem are titled "With eqpt margin" and "With sys margin".
- Each activity names two modes, the payload's and the platform's, written `{payload_mode: imaging, platform_mode: imaging}`, in place of one mode. `Activity.mode` is a `Modes`, with `payload` and `platform`. A scenario file with one mode is refused.
- `run.mode` holds two mode rows, `run.mode["payload"]` and `run.mode["platform"]`. A slew replaces only the platform's mode. In the slew into an activity, the payload keeps the mode of the activity before, or takes the activity's own mode with `payload_mode_in_slew: this_activity` in the activity's modes. The activity table has a payload mode and a platform mode column, and the Gantt chart a row for each.
- The power consumption is in two files, `payload_consumption.csv` and `platform_consumption.csv`, in place of `power_consumption.csv`. Each keeps the old format, with its own group's mode columns, and only the platform's needs a `slew` column. `run_consumption` takes both, by the group's name. `ConsumptionRun` cuts the run where either mode changes, and `mode_watts` gives each group's modes. `python -m quicksat.power` and the editor's server read both files.
- The articulations' park angles go by the platform's mode. A park angle that names a mode only the payload has is refused.
- The viewer shows the payload's and the platform's modes on the timeline, in the current data and in the activity table, and can colour the tracks by either. `scenario.js` has the tracks `payload_mode` and `platform_mode`, and each occurrence's `mode` gives both. `power.js` gives each consumption file in `consumption_files`, and the Power tab's setup has a table of each group's consumption by mode.
- The Scenario Editor lists the payload's modes and the platform's apart, on the Modes step. Each activity picks both, and, with slews, the payload's mode in the slew into it. Each group has its own consumption table, on the Consumption tab and a Setup step each. The editor flags a power folder that holds only one of the two consumption files.
- The power and scenario samples, the reference notebooks and the guides use the two modes and the two consumption files. In the samples, the payload's file holds the mass memory and the X-band transmitter, and the platform's has a `ttc` mode for the Svalbard pass.

### Fixed

- In the Activity Designer, a change made while a run was under way no longer clears "Changed since the last run" when the run ends. The run holds the page as it was when it started, so the bar now says it is out of date. A click on Repeat the list during a run counts as such a change.

## [0.4.0] - 2026-10-23

### Added

- `requirements.yaml`, a sizing file of what the mission asks of the spacecraft. Its `agility` section lists the slews the mission needs, each with its axis, angle and time. Its `data` section gives `orbits_without_downlink`, the longest run of orbits with no payload data downlink, which the mass memory must cover. `Requirements`, in `quicksat.utils.requirements`, reads it. The file and each section are optional. The sample, the reference and the test folders have one.
- `checks()` on the delta-V, data and agility budgets: the propellant loaded against the propellant required, the downlink against the data generated, the mass memory against the storage required, and each slew against its time. A `Check`, in `quicksat.utils.checks`, gives the spare, the margin and the verdict, and `tabulate()` lays checks out. The notebooks show them, in place of the verdicts they worked out in their own cells.
- The Sizing Editor edits `requirements.yaml` on a Requirements tab and a Mission requirements step, the mass memory's capacity, and the selected inertia case.
- The Sizing Editor's Budgets tab shows every sizing budget as quicksat works it out: an overview of each budget's deciding figures and every check, and a page for each budget with the tables its notebook shows. The agility page shows the selected inertia case, and compares the others in a table. Its title counts the budgets with a failing check. `quicksat.editor.budgets` works the budgets out. A page opened from a file shows them as they were when Python wrote it, and says which files have changed since.
- `python -m quicksat.editor serve FOLDER` serves the Sizing Editor for a folder of sizing files, with no output folder. The Budgets tab then follows each change on the page, as the server works out every budget again. The server answers `budgets`, and the page has the Stop the server button.
- The Scenario Editor and the Sizing Editor keep a draft of the changes not saved in the browser's storage. When the page is reloaded or opened again, a bar offers to restore the draft or discard it, and says if a folder file has changed on disk since. A change on the page discards the draft, and it goes once every file is saved.

### Changed

- The data file's `storage` block holds the mass memory's `capacity`, in place of `orbits_without_contact`, which moved to `requirements.yaml` as `orbits_without_downlink`. `DataBudget` and `DataBudget.from_yaml_file` take the requirements. `storage_required()` needs its orbits passed in when the budget has no data requirement. The data table gains a row for the mass memory, and shows the storage required only with a data requirement.
- `agility_config.yaml` names a `selected_case`, which must be one of its inertia cases. `AgilityBudget` and `AgilityBudget.from_yaml_file` fly it when no case is named, and take the requirements.
- `turn_between` takes `toward`, a quaternion for each end, in place of `reference`, one rotation for all of them. `SlewWindow` holds `path_seconds` and `path`, its target attitude sampled through the turn, in place of `end_rotation`.

### Fixed

- A slew no longer jumps partway when its target attitude moves more than a half turn before the turn ends. The way round was chosen against the target at the end of the turn, and it flipped there. With a slew limit slower than nadir's own motion, the body jumped at 7.2 deg/s. Each slew now samples its target every 10 s through the turn, and keeps one way round throughout. Slews at real rates, as in the samples, turn exactly as before.

## [0.3.0] - 2026-10-20

### Added

- The Activity Designer, on the Scenario Editor's Activities tab, with the editor's server. The run sits above the list of activities: the orbit in 3D, the ground track, and the timeline with each target's passes. **Generate scenario** runs the list as it is on the page, and writes nothing. The list runs once at first, or with repeats, and may be empty. Selecting a row shows its activity in the run, and a click on the timeline or the track selects the row. Under each title is what the run made of it, such as a turn faster than the slew block allows.
- **Save into the folder**, on the same tab, writes the scenario file into the server's input folder, after a confirm. It refuses a file that changed on disk since the page read it.
- `run_scenario(scenario, repeat=False)` runs the list of activities once. The time after it is unplanned: `run.unplanned` gives it, and the attitude and mode rows name it `unplanned`. `Scenario.from_yaml_text` and `from_yaml_file` take `designer=True`, which reads an empty list of activities and skips the park mode check.
- `scenario_data(run, designer=True)`, `activity_rows` and `designer_page` give the designer's data, the results of each activity and the page. The editor's server answers `design`, `designer` and `save`.
- The viewer marks each whole orbit on its timelines. Its current data gives the time and the orbits since the start.
- A guide, `docs/guides/scenario/plan_the_activities.md`, builds a list of activities in the Activity Designer, from an empty list to a plan for the whole run, and says what to do about each warning. The scenario reference notebook has a section on one pass of the list and on an empty list.
- A guide, `docs/guides/scenario/prepare_a_3d_model.md`, takes a spacecraft model from CAD or Blender to a GLB file: its axes, units and origin, the parts that turn, the solar panels and the export settings. It checks the model in the Scenario Editor and from Python, and checks the body axes against the attitudes on the editor's Operations tab, so that the imager looks down and the cells face the sun.
- **Stop the server**, at the top right of the Scenario Editor, stops the editor's server after a confirm, as Ctrl+C does in its terminal. A server started with no terminal, such as from a desktop shortcut, can now be stopped too. The server answers `stop`, and stops by itself after 48 h with no editor page open.
- A guide, `docs/guides/sizing/close_the_sizing_budgets.md`, runs every sizing budget in rounds, carries each result into the files by hand, and stops when a round passes every budget and changes nothing. Its example closes a direct re-entry on the sample in four rounds, and its last section covers a change of orbit.
- The README's Quickstart section lists a guide for each task.
- A guide, `docs/guides/scenario/use_a_relay_satellite.md`, plans a link to a data relay: its element sets, the targets, the passes, an attitude or an antenna that points at it, activities that end at its rise and set, and the time it is tracked.
- A guide, `docs/guides/sizing/add_a_manoeuvre.md`, adds a manoeuvre to the delta-V budget: which type to pick, the row, how often it happens, the loss factor, the checks, and its cost in propellant.

### Changed

- No attitude and no mode may be named `unplanned`, as none may be named `slew`.
- `body_rates` gives NaN next to a time with no orientation, where it failed before.

### Fixed

- A slew that must start before an earlier slew now replaces it, since the body turns from where it was and never makes the earlier turn. The list of slews stays in time order, so the viewer's attitude track no longer has a piece that ends before it starts.

## [0.2.0] - 2026-10-17

### Added

- A sun-synchronous orbit takes the local time of the descending node, `ltdn`, in place of `ltan`. The two are 12 h apart. The Scenario Editor's Orbit step has a choice of node, and switching it keeps the orbit.
- Both editors open a folder, or its files, dropped onto the page, and a file dropped onto its tab's bar. The buttons still open the file picker.
- `python -m quicksat init` prints where the input files and everything else went, and the steps to start the editor's server. The README walks through the server step by step.
- The viewer holds every input file of its run. Its Inputs tab now shows the orbit's file, for a TLE, an OMM or a trajectory file, and the power consumption file.
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
- The viewer reads `power.js` version 2 only. With any other version, the page leaves out the power and says why.

### Removed

- The hints for older scenario files. An articulation with `sun_axis`, or an activity list with no title, is now refused as any other mistake is. The Scenario Editor no longer converts them either.
- The viewer's code for older `scenario.js` and `power.js` files, such as the page without an Attitude tab.

### Fixed

- `python -m quicksat init` closes GitHub's response when it falls back to `master`, so Python no longer warns about it.

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

[Unreleased]: https://github.com/egemenimre/quicksat/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/egemenimre/quicksat/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/egemenimre/quicksat/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/egemenimre/quicksat/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/egemenimre/quicksat/tree/v0.1.0
