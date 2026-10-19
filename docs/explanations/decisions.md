# Decisions

The decisions that shaped quicksat, and the reasons for them. A decision belongs here when reversing it would take real work. It also belongs here when the code alone does not show the reasoning. That is the difference between this file and the module docstrings.

Newest first. When a decision replaces an earlier one, the earlier one is kept inside the new entry rather than deleted. Most of the value is in knowing what was tried, and why it was replaced.

---

## 20. The Activity Designer is the viewer in a frame, served by the editor's server

**2026-10-18. Implemented. Changes 18: the server can now save the scenario file.**

The Scenario Editor's Activities tab shows the run above the list of activities. The user edits the list, presses **Generate scenario**, and sees the ground track and the timeline at once. The user goes round many times, from an empty list to a full one.

**The viewer in a frame.** The viewer reads its data once, at load, into about 60 constants. Redrawing it with new data would mean rewriting a page of 3400 lines. So each run loads the viewer's page again, in a frame, with the run's data inside it. The data's `designer` field turns on the designer mode: no header, no body view, and each target's passes under the timeline. The frame and the editor's page come from the same server, so they share an origin. They tell each other which activity is selected, through messages. The frame also reports its time cursor and its zoom, and the page passes them back in the frame's address at the next run.

**Generate writes nothing.** The run happens in a temporary folder, as for Create the viewer. The server keeps the page in memory for the frame. Create the viewer stays the way to write the viewer. The power is not run, since the designer is about the timeline.

**A single pass and an empty list, in the designer only.** At first the list runs once, so the user sees where it ends against the orbit. The time after it is unplanned. The attitude and mode rows give it as `unplanned`, a name that no attitude or mode may take. The body has no orientation then, and the turn rate check looks only at the planned time. Whatever needs the whole run planned refuses such a run: the sun in body axes, and so the power, the articulations, the attitude files, the report and the normal viewer's data. An empty list is read only with `designer=True`. It also skips the check that each park mode is one the activities have, since a list being built may not have it yet. A saved file, the command line and the notebooks still need at least one activity.

**The orbit in 3D, and no body view.** The map is at most twice as wide as it is high, so beside it, the orbit view takes width that the map would leave empty. The user asked for it on 2026-10-18, once that width was measured: at 1440 by 900 pixels, the map took 356 of 1131. The map keeps its height. The body view has no room, so the designer's data leaves out the body's orientation, the roll, pitch and yaw, the joint angles and the model, which keeps each run's page smaller. The orbit view then shows the spacecraft as its marker alone. The data keeps the turn rates, for the amber bands on the timeline. The body view may come back later.

**Saving through the server.** **Save into the folder** writes the scenario file into the input folder, after a confirm. The designer is used round many times, and a download each time would break the loop. Before, decision 18 said: "It does not save the files into the folder. The run takes the files as they are on the page, saved or not, in a temporary folder that it then deletes. Saving is still a download. Saving rewrites every `#` comment, so the user reviews those first." The save keeps that review: the confirm counts the `#` comments written by hand that saving would drop. It refuses:

- a path outside the folder;
- a file whose bytes on disk differ from those the page last read or saved, by SHA-256. Another program or page changed it since. The server works out the hashes when it writes the page, since the page holds the scenario as data, not as its text;
- an empty list, and a scenario that the page did not get from the server's folder.

It writes to a temporary file in the same folder, then renames it, so a failure leaves the old file whole. It takes the same key, `Host` and `Origin` checks as a run.

**Measured on the power sample:** one pass takes 1.6 s, and the run with repeats 3.3 s. The first run after the server starts takes about 20 s more, while astropy loads its tables. So a run waits for the button, and does not follow each key press.

---

## 19. Other satellites are targets, in a block of their own

**2026-10-16. Implemented. Renames `targets` to `gnd_targets`.**

A target can be another satellite, such as a relay of a constellation, as well as a point on the ground. Attitudes and articulations point at it, and its rise and set end activities, as for a ground target. A target is a direction, from the satellite to the target at each step, so the attitudes need no new maths.

**Two blocks, not one.** `gnd_targets` holds the ground points, and `sat_targets` the satellites. The two kinds share no field: a ground point has a latitude, a longitude, an altitude and `min_elevation`, and a satellite has an orbit file and `min_clearance`. In one block, a typo such as `lattitude` would fail against both models, and pydantic would report both. Two blocks cost one check, that no name is in both. They give plainer errors, their own help, and a plainer editor. The rename breaks scenario files written for 0.1.0, which nobody uses yet, so the old key is refused with no message of its own.

**The orbit comes from a file.** A satellite target takes a TLE or OMM file, or a trajectory file, as the scenario's own orbit does. There is no `sso`: it builds an orbit for the scenario's own satellite, and a target's orbit already exists. A TLE or OMM file may hold a group of satellites, as CelesTrak and Space-Track give them. A target takes the one that `object` names, by its name or catalogue number, or else the one of its own name. A given `object` must match a file of one satellite too, so that a wrong file is caught.

**In view.** The line between the two satellites must keep `min_clearance` above the WGS84 ellipsoid, 100 km by default, so that a link does not cross the atmosphere. The test raises the ellipsoid by that height, which stays within 1 m of the true height up to 500 km. Stretching along the Earth's pole then turns it into a sphere, and the line's closest point to the centre is found in closed form. The ellipsoid turns about its pole, so the pole is all the test needs of the Earth's orientation. It is taken once for each call: it moves by about 1e-5 rad in a month. Turning every step into ITRS instead cost 0.28 s a call on the sample's grid, and the pole takes 4 ms.

**No warning for a target out of view.** An attitude that tracks a hidden target points through the Earth, as for a ground target since 2026-10-10. The rise and set triggers end activities at a pass instead.

**The orbits are checked against the run.** An element set more than 7 days from either end of the run gets a warning, and a trajectory must cover the run. The warnings are among the run's own, so the viewer and the editor show them. Before, the epoch warning was a Python warning only, and only the start was checked.

**One satellite for each target.** An activity tracks one target. With a constellation, "point at whichever relay is in view" would need a group, with a rule for when to hand over. The user chose on 2026-10-16 to leave groups out, for the Activity Designer to help choose a relay by hand. A group could come later as a block of its own, which would break nothing, and serve a network of ground stations too.

---

## 18. The Scenario Editor runs quicksat through a local server

**2026-10-15. Implemented.**

`python -m quicksat.editor serve FOLDER OUTPUT` serves the Scenario Editor from the user's own computer. Its **Create the viewer** button sends the page's files to the server. The server runs them with quicksat, and writes the viewer into the output folder. One round of the loop is then: edit, create the viewer, look at it. Before, it was: edit, download, copy the files back, run a command, and open the viewer.

**Why a local server, and not Python in the browser.** Pyodide runs quicksat unchanged in a page, as a spike showed on 2026-10-11. But a browser loads Pyodide only from a web address, so the page would be hosted, for example on GitHub Pages. The run would still happen in the user's browser, and no file would reach the host. But the page's code would come from the host at each visit. A company cannot easily check that this code never sends its files elsewhere, and many companies forbid such tools for their data. A local server keeps the code, the files and the run on the user's computer. It also runs natively, about twice as fast, with no 55 MB to load first. The users are engineers and students, who can install Python and quicksat with pip.

**What the server does not do.**

- **It does not save the files into the folder.** The run takes the files as they are on the page, saved or not, in a temporary folder that it then deletes. Saving is still a download. Saving rewrites every `#` comment, so the user reviews those first. Changed by 20: the Activity Designer saves the scenario file into the folder.
- **It serves the Scenario Editor only.** The Sizing Editor works out its budgets on the page, and needs no run.

**How the server keeps to its user.**

- It listens on 127.0.0.1, which other computers cannot reach.
- Each start makes a random key of 12 characters, which every address ends with: `http://localhost:8780/quicksat/editor?key=k3Xq9vTzR2mA`. A page from another site does not know the key, so it cannot read the folder's files, the viewer's data or ask for a run. The key stays in the address, not in a cookie, because a user can block or delete cookies, and a browser shares them between all the ports of `localhost`.
- The port is 8780, or the next free one, so the address stays the same from one start to the next, apart from the key. The host is `localhost`, as names such as `quicksat.localhost` fail in Safari, and other names need a change to each computer's hosts file.
- It refuses a request whose `Host` is not its own address. This stops a site that points its own name at 127.0.0.1.
- It refuses a run asked by a page from another origin.
- Its pages tell the browser not to send their address, with the key, to other sites, such as the place search.

**The page without a server.** A page opened from a file has the button greyed out, with the command that starts the server. A page from the server asks it every few seconds whether it still answers. When it stops, the button is greyed out, with how to start it again.

**The stop.** The page's **Stop the server** button stops the server, after a confirm, as Ctrl+C does in its terminal. A server started with no terminal, such as from a desktop shortcut, would otherwise run until the user found its process and ended it. The server refuses the stop while a run or a save is going on.

The server also stops by itself after 48 hours with no editor page open, for a user who closes the page and forgets the server. A page asks the server every few seconds while it is in view, and every 10 min while it is not. So a page left open in the background keeps the server going, and a page closed for two days does not.

**After a run,** the page's full check becomes what the loaders said in that run. The server also serves the output folder, so **Open the viewer** opens the new viewer.

A hosted page with Pyodide stays possible, for a demo that needs no install. It would answer the same request as the server.

---

## 17. The editor finds places with Nominatim

**2026-10-15. Implemented. Replaces a list of places held in the page.**

The Ground targets step has a search box that asks OpenStreetMap's Nominatim. It finds any address, and many ground stations by their own names, such as SvalSat. The page sends the search text to openstreetmap.org, and needs a connection for it. Without one, the user types the position in, as before.

Nominatim's usage policy sets how the page asks. It allows at most one request a second, and no search as the user types. So a search runs on Enter or its button, waits a second after the last one, and keeps its answers for the session. The page credits OpenStreetMap beside the box.

The page first held Natural Earth's 1:10m populated places: 7,342 towns and cities, 514 kB, offline. A town's position is its centre, and a station can lie far from it: Kiruna town is about 30 km from ESA's station. The list made each scenario page half a megabyte larger, and found no station by name. So it was deleted.

---

## 16. The editor also opens files in the browser

**2026-10-14. Settled.**

Each editor page has an **Open a folder** button on its first Setup step, and an **Open** button on each tab for that tab's file. The page reads the files itself. So one page can edit any folder, and it need not be written again after the files change. Entry 14 left this for later.

- **The YAML is read with js-yaml,** a 39 kB library that the page holds. It takes YAML's core types and merge keys, the nearest it comes to PyYAML. The two differ on a few forms, such as `yes`, which PyYAML reads as true. One of them matters to quicksat: PyYAML reads an unquoted `13:30` as the number 810, and the page reads it as the text. The page writes it in quotes, as quicksat needs it.
- **The `#` comments are found by the page,** with the same rules as Python's. A test checks that they agree, on some awkward layouts and a copy of quicksat's own YAML files. Python's answers are kept in a file, so the test runs in CI's Node job (2026-10-15).
- **quicksat's loaders do not run** on a file opened in the browser. The page shows two checks for each file: the simple check, its own, and the full check, what the loaders said when Python wrote the page. A file opened since has *not run* as its full check.
- **Saving is still a download.** Writing back into the folder works in Chrome and Edge only, so it is left for later.

Python still writes the page for a folder, with its loaders' checks: the samples' pages are made that way.

**Extended on 2026-10-15.** The Sizing Editor, which entry 14 planned, is built from the same shared parts: `python -m quicksat.editor` writes it for a folder of sizing files. Each page's first step lists the folder's files, and each tab has a bar for its own. Both say where each file came from, and whether it has changed since it was opened or saved. A file has changed when the text the page would save differs from the text it had then, so a field set back to its value counts as unchanged. **download** on a tab saves that file alone. The Sizing Editor saves every budget's files, as a zip or one by one. It has no switch to leave a budget out: a folder that lacks a budget's files gets them started on the page, as new (2026-10-15).

A file opened alone shows no folder: a browser does not tell the page where it came from.

---

## 15. An articulation points an axis at any direction

**2026-10-13. Settled.**

An articulation was first a part that turns to face the sun, with `sun_axis` naming the axis that faces it. It is now written `point: [-z, sun]`: the axis, and the direction to turn it toward. The direction is any that an attitude can use: the sun, nadir, the orbit normal, the velocity, the ground velocity, or a ground target. So an antenna on a one-axis drive can follow a ground station, with the same rule as a wing that follows the sun.

The form matches the attitudes', so the file has one way to name an axis and its direction. A file that still says `sun_axis` is refused. A second spacecraft as a direction would need a second orbit, which quicksat does not have.

---

## 14. The editor is a page that holds the folder's files

**2026-10-13. Settled.**

The input files can be edited in a web page, written by `quicksat.editor` for one folder of files. The page opens from disk, with no Python and no server, as the scenario viewer does. Python reads the folder when it writes the page, and puts the files inside it: the YAML as YAML reads it, the CSV as text, the 3D model in base64. The page turns them into its fields, and saving downloads the files again.

The page was chosen over three other ways to give it the files:

- **Reading the files in the browser,** picked or dragged in, would need a YAML reader in JavaScript, and a second reading of every file. It may come later.
- **A local server** would need Python running beside the page.
- **Python in the browser,** with Pyodide, runs quicksat unchanged, but makes the page some 55 MB to fetch. It is the likely way to add a Run button later.

So the page checks only names, units and ranges. When Python writes the page, it also reads the files with quicksat's own loaders, and the page shows what they said. A run is still needed for the full checks.

**One folder, one page.** A scenario folder and a power folder each get their own page, as each domain keeps its own files (entry 9). A power folder's page edits the scenario, the power system and the consumption together. The sizing files will get a page of their own, because their reference orbit is not the scenario's orbit, and one page would invite the user to think they are linked.

**Extended on 2026-10-16: the help in one file per domain.** The page's information boxes and the `#` help lines it writes into saved files were two copies in the page's scripts. They now sit in `quicksat/editor/help/`: `scenario.yaml`, `power.yaml` and `sizing.yaml`. Each key holds a step's title and information box, the help written above a key of the file, or both. Python puts the files of a page's domains inside the page as JSON. The reference notebooks stay the full explanation. Whether pydantic's field descriptions should also come from these files is left open.

---

## 13. The user's notes live in `comments` fields

**2026-10-13. Settled.**

Every block of an input file may hold a `comments` field: the orbit, each attitude, each target, each articulation, each panel, the battery, and so on. So may the file as a whole, and each section of named items, such as `attitudes`. An activity takes the map form to hold one: `{title, end, attitude, mode, constraint, comments}`. The CSV files already had a `comments` column. quicksat keeps the notes and does not read them.

The reason is the editor (entry 14). It rewrites the files when it saves them, and a `#` comment is not data: no YAML reader keeps it. A `comments` field is data, so every tool keeps it. The `#` lines are left to the editor's own help, which it rewrites on each save. When the page opens, it lists the `#` comments that it did not write, and moves the ones the user chooses into the `comments` field of their block.

An earlier proposal kept the user's `#` comments, and marked the editor's help with `#|`. It needed a YAML reader in JavaScript that keeps comments, and it would still lose them to any other tool that rewrote the file. It was dropped.

Since a section's notes sit under the key `comments`, no item may take that name.

**Extended on 2026-10-14.** The sizing files take `comments` fields too, in every block. Their YAML files now refuse a key they do not know, as the scenario and power files do. Before, a typo in an optional key, such as `return_brn: false`, left the default in place with no warning. The CSV files still accept columns of their own.

**A `#` comment goes on the lines above what it describes,** not at the end of a line. A block of comment belongs to the key below it. With a blank line between them, it belongs to the section that holds that key, or to the whole file. quicksat's own files were rewritten in this style on the same day. A comment at the end of a line still goes to the key on that line, but one that runs on to the next lines is split.

---

## 12. The power losses sit in three places, and a slew is a mode

**2026-10-11. Settled.**

**The losses are counted once, where they happen.** A first-pass budget often takes one efficiency for the whole power system. quicksat splits the losses into three places instead:

1. **Up to the array's output:** `loss_factor` in the power system file. It takes the cells' temperature, ageing, mismatch between cells, UV and the array's own wiring, set for the year being sized. There is no loss per year and no temperature model: the user sets the factor.
2. **The power conditioning:** one efficiency for each path the energy takes after that. From the array to the bus, into the battery, out of the battery, and from the bus to the loads.
3. **Fixed overheads, as loads:** the power unit's own electronics and the heaters are rows of the consumption file.

The reason is that energy routed through the battery pays both its paths, about 10%, and the rest does not. One efficiency for the whole system would hide that, and would understate a long eclipse. The split also keeps each loss in the file of the person who knows it.

**The battery and the conditioning sit in the power system file,** with the panels. The file was first `power_generation.yaml`, and was renamed when they joined it. The consumption has its own CSV, since it is a long list.

**Each orbit must have energy to spare.** The budget checks that the battery's charge stays above its limit, and that each whole orbit has a margin of zero or more. The margin counts the energy that a full battery could not take as if it had taken it. So it does not depend on where in the orbit the window starts, nor on how full the battery is. The charge limit alone is not enough: a run that starts full can stay above it for a few orbits while losing energy every orbit.

**A slew is a mode of its own.** During each slew, the run's mode row says `slew`, as its attitude row does. The slew takes the end of the activity before it, so the payload is not at its task then. The consumption file then gives the slew its own column, which the user fills: it is never assumed to equal another mode. `slew` is a reserved mode name. The alternative, a `slew` column that overrides the mode for some equipment only, was dropped as harder to read.

---

## 11. The solar panels come from the 3D model

**2026-10-08, agreed. Built on 2026-10-11.**

A panel in the power system file, `power_system.yaml`, names its part in the scenario's 3D model, such as `Wing +y inner cells`. quicksat reads the part's triangles from the GLB file, and takes the panel's area and normal from them. The part must be flat, so the face of cells is a part of its own.

Entry 9 first gave each panel a named face, such as `+x`. The model replaced that for three reasons:

- **The geometry is typed in once.** The model already holds the panels' sizes and directions, for the viewer.
- **Turning panels follow the model.** A panel under an articulation's node, such as a wing panel, turns with that articulation. The node tree says which, so the power file does not repeat it.
- **Self-shadowing needs the shapes.** A part that lies between a panel and the sun shades it, and only the model knows where the parts are.

**Typed-in panels are kept,** with a normal and an area, for a scenario with no model, or a model with no clear panels. They also let a panel be tried without editing the model. They have no shape, so they stay fixed in body axes, are never shaded, and shade nothing. The run notes each one in its output, as text, so that the two kinds are not mixed without the user knowing.

**The self-shadowing needs no new package.** All rays at one step share the sun's direction, so the model is projected along it, and each sample point is tested against the projected triangles. trimesh would do it, but would be a new dependency, and its fast engine is hard to install on Windows. Strings of cells are not modelled: quicksat gives a first-pass sizing.

---

## 10. Scenario is its own domain, and power depends on it

**2026-10-02. Settled.**

A third domain, `scenario`, sits next to `sizing` and `power`. It follows the layout in entry 9: `sample/scenario/`, `docs/scenario/`, `tests/scenario/` and `docs/guides/scenario/`, with the code in `quicksat/scenario/`.

The scenario holds the orbit, the start time, the duration and a list of activities. Each activity has an end trigger, an attitude, a mode and an optional constraint. The scenario file is `scenario.yaml`. The scenario notebook checks the activities against the orbit, for example their eclipse constraints.

**The dependency runs one way.** The scenario imports nothing from power. Power imports the scenario. The workflow follows from that:

1. Define the scenario.
2. Define a baseline power sizing: the solar panels and the batteries.
3. Verify that the sizing supports the scenario.

The reason is that a scenario of modes and attitudes is useful without a power model. Other domains may use it later, such as thermal, or agility along the scenario's real attitudes.

**Power keeps its own copies of the scenario files.** Power imports the scenario code, but it does not read the scenario domain's files. Each power data folder holds the scenario files it needs, so `sample/power/data/` never reads `sample/scenario/data/`. This keeps the rule in entry 9 that the domains do not share input files. One power setup can be checked against more than one scenario, such as winter and summer, so a power data folder may hold several scenario files.

**The scenario names the modes, and power defines them.** An activity says `idle` or `firing`. The power files say how much each mode draws. Power checks that every mode in the scenario has a consumption entry.

**An unsupported scenario is a power result.** A battery that runs flat is reported by power. It is not a scenario error. The scenario is invalid only for its own reasons, such as a violated constraint.

**Visualisation is not a domain.** Plots that compute a result stay in the notebook of the domain that owns the data. A scenario viewer is a separate front end. It reads a timeline file written by the library and, optionally, the power results. Which technology it uses is decided elsewhere.

---

## 9. Sizing, scenario and power are separate domains, each with its own files

**2026-10-01. Settled. Updated on 2026-10-08: entry 10 added the scenario as a third domain on 2026-10-02.**

The notebooks, their input files and the tests are split into domains. `sizing` holds the current four budgets: mass, data, delta-V and agility. `scenario` holds the orbit and the timeline of activities. `power` holds power generation. Each domain has the same three folders:

- `sample/<domain>/` for the worked examples, with their data in `data/`.
- `docs/<domain>/` for the reference notebooks, with their data in `data/`.
- `tests/<domain>/` for the tests, with their fixtures in `data/`.

The how-to guides follow the same split, under `docs/guides/<domain>/`. Project-wide documents stay at the top of `docs/`: this file and `reference/conventions.md`.

The reason is that the domains describe the satellite differently. Sizing uses a circular orbit and a flat equipment list. The scenario needs an epoch, a local time of the ascending node, and a TLE or an ephemeris. Power needs solar panels on named faces, and takes its orbit from the scenario. One set of files cannot serve them all without a domain carrying fields it never reads.

When this entry was written, there were two domains, sizing and power. The orbit and the epoch were then power's. Entry 10 moved them into the scenario.

**The domains do not share input files.** The rule in entry 2 applies within a domain: a fact that more than one module in that domain uses goes in that domain's shared file. The domains may share code, such as the orbit and sun geometry in `quicksat/orbit/`, but not data. The three copies in entry 5 are kept once per domain.

---

## 8. Earth constants are astropy's defaults

**2026-09-30. Settled. Replaces WGS-84 and EGM96, which the project used from the start.**

`R_EARTH` and `MU_EARTH` are now astropy's `R_earth` and `GM_earth`. By default these are the IAU 2015 nominal values, 6378.1 km and 398600.4 km³/s². Before, quicksat wrote out its own: the WGS-84 equatorial radius of 6378.137 km, and the EGM96 measured GM of 398600.4418 km³/s². astropy is now the one source of physical constants, as it already was for standard gravity.

The change is too small to matter for sizing. At 500 km, the orbital period moves by 0.05 s and the velocity by 0.02 m/s. One test checked the orbit radius to the metre, and it was updated. Every other figure in the tests, the README and the notebooks is unchanged at the precision it is quoted to.

`MU_EARTH` is still a GM rather than G times a mass. GM is the measured quantity, known to about nine significant figures. G is known to about five. astropy works the same way: it derives its `M_earth` from GM and G.

---

## 7. Orbit, attitude and sun geometry with astropy, not orekit

**2026-09-30. Settled, after measurement.**

The power budget needs the angle between a solar panel's normal and the sun. That angle needs a trajectory, an attitude, and the sun's position. The candidates were astropy, and Orekit through one of its two Python wrappers.

**astropy.** It supplies three of the four pieces. These are the sun (`get_sun`), the inertial and Earth-fixed frames (`GCRS`, `ITRS`, `TEME`), and a frame graph that chains rotations together. It supplies **no propagator and no attitude model**, so quicksat writes those. They take about 120 lines. `LVLH` and `Body` can be real `BaseCoordinateFrame` subclasses, with the spacecraft state as frame attributes. Then `get_sun(t).transform_to(body)` is the whole calculation.

**Orekit.** It supplies all four, and its domain objects are good, such as `NadirPointing`, `EcksteinHechlerPropagator`, `EclipseDetector` and `BoxAndSolarArraySpacecraft`. But it needs a JVM.

Both were installed and run on the same problem, and they agree. The eclipse fraction is 0.3776 against 0.3782, and the mean panel cosine is 0.3177 against 0.3169. The small difference has two causes. The astropy side used J2-only secular drift, against Eckstein-Hechler's J2 to J6. The two also use different sun ephemerides. Orekit's `NadirPointing` gave **exactly** the LVLH convention that had been chosen by hand. This was the most reassuring single result of the comparison.

**astropy was chosen because it is easier to install, and that is the deciding constraint.** Some users will install quicksat on Windows.

- Installing Java is *not* the problem. conda-forge installs a JVM automatically on every platform. The problem is **finding** the JVM. JPype searches `JAVA_HOME`, and then two registry keys that only an old Oracle JRE writes. Temurin, Adoptium and Microsoft OpenJDK write neither of them. conda sets `JAVA_HOME` only on `conda activate`. So an interpreter started without activation does not find the env's own JVM, and gives no clear reason. VS Code may start an interpreter this way, and so does Jupyter launched from a plain prompt. Each such user would need support, for a library that installed without an error.
- Orekit also needs `orekit-data`, which is 21 MB zipped and 37.7 MB unpacked. It is not a package on either channel, so it must be downloaded at setup.
- Performance would not have decided it. A power run covers one orbit to a day or two. One day at 10 s steps through SGP4 takes 1.9 s in astropy. Orekit takes 1.3 s for the loop, plus 1.1 s to start the JVM. astropy's one slow step is its TEME to GCRS transform for each sample. A single rotation per run could replace it, and would be 7 times faster. This is not done, on purpose. The code is not meant for long sweeps, and the gain does not matter at the scale it is meant for.

**If Orekit is ever needed, use `orekit_jpype`, never the classic JCC `orekit`.** The JCC wrapper has three problems. It rejects `np.float64`, and its error does not name the argument. It lacks methods that the Java API has: `Vector3D.normalize()`, for example, raises `AttributeError`. *Yet its own generated stubs list them*, so Pylance offers methods that fail at runtime. And it is pinned to Java 8. JPype also turned out to be the faster of the two, contrary to what is usually said.

The full assessment, the numbers and the working code are in `.claude/power_spike/`.

**Consequence.** `astropy` and `sgp4` join the dependencies. quicksat maintains its own orbit and attitude code. This is accepted, because the code has been checked against Orekit, rather than only looking plausible.

---

## 6. astropy.units, not pint

**2026-09-30. Implemented. Replaces pint, which the project used from the start.**

quicksat began with pint. `quicksat/__init__.py` exported a single `UnitRegistry`, with a `Q_` shorthand. Units were parsed when the files were loaded. Inside the DataFrames, they were stripped to floats in standard units. Every column in a mass budget has one dimension, so a unit dtype in the frame added little. It would also have tied the project to `pint-pandas` compatibility.

**astropy replaced it, because the power generation work needs astropy for the orbital mechanics** (decision 7). astropy.units comes with it, wanted or not. `get_sun`, every frame and every representation return an `astropy.units.Quantity`. So the choice was between two unit systems with a boundary between them, and one.

astropy is weaker in one place: offset units. pint's `Q_(25, "degC")` is unambiguous. astropy needs `u.deg_C`, which has its own handling. The radiator work will need offset units. This is known and accepted, and will be handled then.

Three conventions from the pint era carry over unchanged. None of them depends on which library holds the units. One is about how numpy dispatches, one about how a notebook reads, and one about where a plain number is allowed. They are in [conventions.md](../reference/conventions.md).

---

## 5. Three copies of the input files, one per audience

**2025-09. Settled.**

`sample/sizing/data/` belongs to the worked examples, and `docs/sizing/data/` to the reference notebooks. `tests/sizing/data/` holds the test fixtures. Before the split, changing the sample to make a budget close would also change a test's expected figure, with no warning. The cost is that a schema change has to be made three times. If one copy is missed, a reference documents a column that its own example file does not have.

---

## 4. The notebooks are the documentation

**2025-09. Settled.**

There are two notebooks per module. `sample/<domain>/<module>.ipynb` is the worked example, which takes one satellite from start to end. `docs/<domain>/<module>_ref.ipynb` is the reference. It covers every column and config key, and where the module stops. So the project needs no Sphinx.

Prose inside a notebook is stored in JSON, so its diffs are hard to read. Executed notebooks also put their outputs into the diff. In return, the explanation cannot go out of date unnoticed. Re-executing a notebook checks every claim it makes against the real code. This needs two habits. First, re-execute every notebook that a change can affect, not only the edited one. Second, check the stored output for tracebacks, because a notebook that ends in an error still saves without complaint.

---

## 3. Shared objects are passed in, never imported and constructed

**2025-09. Settled.**

A budget's constructor takes the object. Its `from_*` classmethod takes paths, for convenience. So a notebook can load `mission.yaml` once, and pass the same `Mission` to every budget. Otherwise each budget would read its own copy, and the copies would only happen to agree. The one link between budgets is `DeltaVBudget(..., mass_budget=None)`. It stays optional, one-way and read-only. A test checks that it is optional, so a later change cannot make it required without the test failing.

---

## 2. One shared mission file, and the rule for what goes in it

**2025-09. Settled.**

**A fact that more than one module can use goes in `mission.yaml`. A fact that only one module uses stays in that module's own config.** So the altitude is shared, and the Isp is not. The earlier rule was that *each module's own config holds only what is specific to it*. That rule had put the design life in `delta_v_config.yaml`. It said where a fact may go, but not which file holds a fact that two modules share.

`duration` is required. A file that says where the spacecraft is, but not how long it stays there, describes an orbit rather than a mission.

---

## 1. The orbit is circular, and stays that way

**2025-09. Settled.**

Nothing models eccentricity, perturbations or drag. This is a first-pass sizing tool.
