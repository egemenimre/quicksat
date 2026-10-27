// ---------------------------------------------------------------- Activities, inputs and results

function statusClass(status) {
  if (status === "ok") return "status-ok";
  if (status === "outside constraint" || status === "negative duration") return "status-fail";
  if (status === "event never came" || status === "slew starts early") return "status-warn";
  return "status-plain";
}

function activitySummary() {
  const count = (status) => OCCURRENCES.filter((o) => o.statuses.includes(status)).length;
  const repeats = OCCURRENCES[OCCURRENCES.length - 1].repeat;
  return (
    `Occurrences: ${OCCURRENCES.length} in ${repeats} repeats. Negative duration: ${count("negative duration")}. ` +
    `Outside constraint: ${count("outside constraint")}. ` +
    `Event never came: ${count("event never came")}. Cut at end: ${count("cut at end")}. ` +
    `Slew starts early: ${count("slew starts early")}.`
  );
}

function showActivities() {
  $("#activities-file").textContent = SCENARIO_FILE;
  $("#activity-summary").textContent = activitySummary();
  const swatch = (value) => [element("span", { class: "dot", style: `background:${colourOf(value)}` }), value];
  $("#activity-rows").replaceChildren(
    ...OCCURRENCES.map((o) =>
      element(
        "tr",
        {
          title: "Show this activity on the Scenario page",
          onclick: () => {
            setTime(o.start_s);
            showPage("scenario");
          },
        },
        [
          element("td", { class: "num", text: String(o.repeat) }),
          element("td", { class: "num", text: String(o.number) }),
          element("td", { text: o.title || "" }),
          element("td", { text: utcText(o.start_s) }),
          element("td", { text: utcText(o.end_s) }),
          element("td", { class: "num", text: `${((o.end_s - o.start_s) / 60).toFixed(2)} min` }),
          element("td", { text: o.trigger }),
          element("td", {}, swatch(o.attitude)),
          // slew_s is null where the activity has no slew
          element("td", { class: "num", text: o.slew_s == null ? "" : `${numberText(o.slew_s, 1)} s` }),
          element("td", {}, swatch(o.mode.payload)),
          element("td", {}, swatch(o.mode.platform)),
          element("td", { text: o.constraint || "" }),
          element("td", { class: "num", text: o.outside_s === null ? "" : `${numberText(o.outside_s)} s` }),
          element(
            "td",
            {},
            o.statuses.flatMap((status, j) => [...(j ? [", "] : []), element("span", { class: statusClass(status), text: status })]),
          ),
        ],
      ),
    ),
  );
}

/** The distance in days of an epoch, in UTC, from the start and the end of the run, and whether either is past 7 days. */
function epochNote(epoch) {
  const at = (Date.parse(`${epoch}Z`) - START_MS) / 1000;
  const from = (seconds, end) => `${numberText(Math.abs(seconds) / 86400, 1)} d ${seconds < 0 ? "before" : "after"} the ${end}`;
  const far = Math.max(Math.abs(at), Math.abs(at - T_END)) > 7 * 86400;
  return [`${from(at, "start")}, ${from(at - T_END, "end")}`, far];
}

/**
 * The Targets page's tables: every pass, in time order, and where each target
 * is or where its orbit came from. A click on a pass moves the time cursor to
 * its start.
 */
function showTargets() {
  if (!TARGETS.length) return;
  // the time in the pass that the body or a part points at the target
  const pointedText = (pass) => {
    const seconds = sharedSeconds(POINTED[pass.target.name] || [], pass.start_s, pass.end_s);
    return seconds ? `${(seconds / 60).toFixed(2)} min` : "";
  };
  $("#pass-rows").replaceChildren(
    ...PASSES.map((pass) =>
      element("tr", { title: "Move the time cursor to the start of this pass", onclick: () => setTime(pass.start_s) }, [
        element("td", {}, [element("span", { class: "dot", style: `background:${targetColour(pass.target)}` }), pass.target.name]),
        element("td", { text: utcText(pass.start_s) }),
        element("td", { text: utcText(pass.end_s) }),
        element("td", { class: "num", text: `${((pass.end_s - pass.start_s) / 60).toFixed(2)} min` }),
        element("td", { class: "num", text: pointedText(pass) }),
        element("td", { class: "num", text: pass.closest_km == null ? "" : `${Math.round(pass.closest_km).toLocaleString("en")} km` }),
      ]),
    ),
  );
  if (!PASSES.length) $("#vp-passes").append(element("p", { class: "none", text: "No target comes into view in the run." }));
  const line = (text, cls = "") => element("div", { text, title: text, class: cls });
  $("#target-sources").replaceChildren(
    ...TARGETS.map((target) => {
      const seconds = target.passes.reduce((sum, pass) => sum + pass.end_s - pass.start_s, 0);
      const count = target.passes.length;
      const spans = POINTED[target.name] || [];
      const pointed = spans.reduce((sum, span) => sum + span.end_s - span.start_s, 0);
      const lines = [
        line(`${count} pass${count === 1 ? "" : "es"}, ${(seconds / 60).toFixed(1)} min in view`),
        line(spans.length ? `pointed at for ${(pointed / 60).toFixed(1)} min, ${spans.length} time${spans.length === 1 ? "" : "s"}` : "not pointed at"),
      ];
      if (target.kind === "ground") {
        const place = `${Math.abs(target.latitude_deg)}°${target.latitude_deg >= 0 ? "N" : "S"}, ${Math.abs(target.longitude_deg)}°${target.longitude_deg >= 0 ? "E" : "W"}`;
        lines.unshift(line(`ground, ${place}, ${numberText(target.altitude_km * 1000, 0)} m`), line(`min elevation ${numberText(target.min_elevation_deg)}°`));
      } else {
        const source = target.source;
        const where = [source.file, ...(source.element_set ? [source.element_set] : [])].join(" · ");
        lines.unshift(line(`satellite, ${where}`), line(`min clearance ${numberText(target.min_clearance_km)} km`));
        if (source.epoch) {
          const [note, far] = epochNote(source.epoch);
          lines.splice(1, 0, line(`epoch ${source.epoch.replace("T", " ").slice(0, 16)} UTC: ${note}`, far ? "far" : ""));
        } else {
          lines.splice(1, 0, line(`trajectory from ${source.start.replace("T", " ").slice(0, 16)} to ${source.end.replace("T", " ").slice(0, 16)} UTC`));
        }
      }
      const name = element("b", {}, [element("span", { class: "dot", style: `background:${targetColour(target)}` }), target.name]);
      return element("div", { class: "source" }, [name, ...lines]);
    }),
  );
}

function kv(pairs) {
  return element(
    "dl",
    { class: "kv" },
    pairs.flatMap(([label, value]) => [element("dt", { text: label }), element("dd", { text: String(value), title: String(value) })]),
  );
}

function block(title, children, wide = false) {
  return element("div", { class: "block" + (wide ? " wide" : "") }, [element("div", { class: "section-title" }, title), ...children]);
}

/** A file's text, with its YAML comments dimmed. */
function fileText(text) {
  const pre = element("pre", { class: "file" });
  for (const line of text.split("\n")) {
    const match = line.match(/(^|\s)#.*$/);
    if (match) {
      pre.append(line.slice(0, match.index + match[1].length), element("span", { class: "comment", text: match[0].slice(match[1].length) }));
    } else {
      pre.append(line);
    }
    pre.append("\n");
  }
  return pre;
}

/** The Power page's setup panel: each block of power.js's setup, as a small table or a list. */
function showPowerSetup() {
  if (!power) return;
  const panelIndex = new Map(PANELS.map((panel, j) => [panel.name, j]));
  // A table's first column names the rows. A panel's name gets the colour of its line.
  const cell = (text, column) => {
    const j = column === 0 ? panelIndex.get(text) : undefined;
    return element("td", {}, j === undefined ? [text] : [element("span", { class: "swatch", style: `background:${panelColour(j)}` }), text]);
  };
  const blocks = power.setup.map((part) =>
    element("div", { class: "setup-block" }, [
      element("div", { class: "section-title", text: part.title }),
      part.columns
        ? element("table", { class: "setup" }, [
            element("thead", {}, [element("tr", {}, part.columns.map((column) => element("th", { text: column })))]),
            element("tbody", {}, part.rows.map((row) => element("tr", {}, row.map(cell)))),
          ])
        : kv(part.items.map((item) => [item.label, `${item.value} ${item.unit}`.trim()])),
    ]),
  );
  const note = power.setup ? `From ${power.power_file}. The file itself is on the Inputs tab.` : "power.js gives no setup.";
  $("#power-setup").replaceChildren(...blocks, element("p", { class: "note", text: note }));
}

/** Give the user a text file, as a download. */
function saveText(name, text) {
  const link = element("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

/**
 * The Attitude page's side: a button that downloads the attitude file, one for
 * each articulation's file, and the warnings. The files' texts come in
 * scenario.js, as quicksat writes them.
 */
function showAttitude() {
  const [attitudeFile, ...jointFiles] = Object.keys(ATTITUDE.files);
  const button = (file, label, help) =>
    element("button", { class: "toggle", "data-help": help, onclick: () => saveText(file, ATTITUDE.files[file]) }, [
      element("b", { text: label }),
      ` · ${file}`,
    ]);
  $("#attitude-files").replaceChildren(
    button(attitudeFile, "Attitude", "downloadAttitude"),
    ...jointFiles.map((file, j) => button(file, ARTICULATIONS[j] ? ARTICULATIONS[j].name : file, "downloadArticulation")),
    element("p", { text: "Each file's header gives the epoch, the time scale, the frame and the quaternion's convention." }),
  );
  const warnings = scenario.warnings;
  const unchecked = ATTITUDE.max_rate_deg_s === null && ATTITUDE.max_acceleration_deg_s2 === null;
  $("#attitude-warnings").replaceChildren(
    ...(warnings.length
      ? warnings.map((text) => element("p", { text }))
      : [element("p", { class: "none", text: unchecked ? "None. The scenario has no slew block, so there are no limits to check." : "None. Every attitude stays within the slew block's limits." })]),
  );
}

function showInputs() {
  const name = (title, file) => [title, " · ", element("b", { text: file })];
  const orbit = scenario.orbit;
  // Two columns: the scenario file and the orbit's file on the left; on the
  // right, the orbit, the target files, the conventions, and the power and
  // consumption files
  const column = (blocks) => element("div", { class: "stack" }, blocks);
  // The orbit's file and the consumption files. None is YAML, so no line is
  // dimmed, and a long file scrolls in its box.
  const plainText = (text) => element("pre", { class: "file tall", text });
  const orbitFile = scenario.orbit_text != null ? [block(name("Orbit file", scenario.orbit_file), [plainText(scenario.orbit_text)])] : [];
  // The satellite targets' files, each once
  const targetFiles = scenario.target_files.map((file) => block(name("Target file", file.name), [plainText(file.text)]));
  const consumptionFiles = power
    ? ["payload", "platform"]
        .map((group) => [group, power.consumption_files[group]])
        .filter(([, file]) => file.text != null)
        .map(([group, file]) =>
          block(name(`${group[0].toUpperCase()}${group.slice(1)} consumption file`, file.file || `the ${group}'s file`), [plainText(file.text)]),
        )
    : [];
  const orbitBlock = block(
    ["Orbit"],
    [
      kv([
        ["Name", orbit.name || "none given"],
        [orbit.tle ? "Nodal period" : "Period", `${numberText(PERIOD / 60)} min`],
      ]),
      ...(orbit.tle
        ? [
            element("p", { class: "note", text: "The element set, as SGP4 reads it:" }),
            element("pre", { class: "file", text: orbit.tle.join("\n") }),
          ]
        : [
            element("p", { class: "note", text: "The states come from a trajectory file, interpolated between its samples:" }),
            kv([
              ["File", orbit.trajectory.file || "none given"],
              ...(orbit.trajectory.format ? [["Format", orbit.trajectory.format]] : []),
              ...(orbit.trajectory.originator ? [["Written by", orbit.trajectory.originator]] : []),
              ["Frame", orbit.trajectory.frame],
              ["Samples", orbit.trajectory.samples],
              ...(orbit.trajectory.segments > 1 ? [["Segments", orbit.trajectory.segments]] : []),
              ["From, UTC", orbit.trajectory.start],
              ["To, UTC", orbit.trajectory.end],
              ["Period from", orbit.trajectory.period_from],
            ]),
          ]),
    ],
  );
  const conventions = block(
    ["Conventions"],
    [
      element("p", {
        class: "note",
        text:
          "Vectors are in GCRS. q_body turns body vectors into GCRS, and q_earth turns ITRS vectors into GCRS. " +
          "LVLH: x along track, y minus the orbit normal, z nadir. The shadow is cast by the sun's disk on " +
          "the WGS84 ellipsoid, with an umbra and a penumbra. With a slew block, the body turns between attitudes; without one, attitude changes are instant. Between time steps the page interpolates position " +
          "and attitude; the power values are per step. Times are UTC, as the start plus the seconds; a " +
          "browser ignores leap seconds. These inputs come from the scenario and power files on this page: " +
          "edit them there and run the notebook again.",
      }),
    ],
  );
  const powerFile = power ? [block(name("Power file", power.power_file), [fileText(power.power_text)])] : [];
  const thermal = power && power.thermal;
  const thermalFile =
    thermal && thermal.text != null ? [block(name("Thermal file", thermal.file || "the payload's thermal file"), [fileText(thermal.text)])] : [];
  $("#inputs").append(
    column([block(name("Scenario file", SCENARIO_FILE), [fileText(scenario.scenario_text || "")]), ...orbitFile]),
    column([orbitBlock, ...targetFiles, conventions, ...powerFile, ...consumptionFiles, ...thermalFile]),
  );
}

function showResults() {
  const count = (status) => OCCURRENCES.filter((o) => o.statuses.includes(status));
  const outside = count("outside constraint");
  const neverCame = count("event never came");
  const negative = count("negative duration");
  const constrained = OCCURRENCES.filter((o) => o.constraint !== null);
  const name = (o) => `Activity ${o.number} of repeat ${o.repeat}${o.title ? `, ${o.title}` : ""}`;

  const eclipses = ECLIPSES;
  // Both times are rounded to 1 ms, so a run of 3 orbits can come out a hair short
  const whole = Math.floor(T_END / PERIOD + 1e-6);
  const span = whole ? whole * PERIOD : T_END;
  const dark = eclipses.reduce((sum, p) => sum + Math.max(0, Math.min(p.end_s, span) - p.start_s), 0);
  const full = eclipses.filter((p) => p.start_s > 0 && p.end_s < T_END);
  const longest = full.reduce((most, p) => Math.max(most, p.end_s - p.start_s), 0);
  const range = (array) => [Math.min(...array), Math.max(...array)];
  const [betaLow, betaHigh] = range(BETA);
  const altitudes = Array.from({ length: N }, (_, i) => Math.hypot(R[3 * i], R[3 * i + 1], R[3 * i + 2]) - R_E);
  const [altLow, altHigh] = range(altitudes);

  const cards = [
    ["Occurrences", OCCURRENCES.length, ""],
    ["Outside constraint", outside.length, ""],
    ["Eclipse fraction", (100 * dark / span).toFixed(1), "%"],
    ...(power ? power.summary.filter((item) => item.headline).map((item) => [item.label, item.value, item.unit]) : []),
  ];
  const checks = [
    {
      name: "Triggers",
      status: negative.length ? "fail" : "ok",
      detail: negative.length
        ? negative.map((o) => `${name(o)}: ${o.trigger} ends it before it starts, so it takes no time`).join("\n")
        : "Every activity ends after it starts.",
    },
    {
      name: "Constraints",
      status: outside.length ? "fail" : "ok",
      detail: outside.length
        ? outside.map((o) => `${name(o)}: ${numberText(o.outside_s)} s outside ${o.constraint}`).join("\n")
        : `All ${constrained.length} occurrences with a constraint stay inside it.`,
    },
    {
      name: "Events",
      status: neverCame.length ? "warn" : "ok",
      detail: neverCame.length
        ? neverCame.map((o) => `${name(o)}: ${o.trigger} never came, so it runs to the end`).join("\n")
        : "Every event trigger found its event.",
    },
    {
      name: "Orbits",
      status: scenario.orbit_warnings.length ? "warn" : "ok",
      detail: scenario.orbit_warnings.length
        ? scenario.orbit_warnings.join("\n")
        : "No element set is more than 7 days from the run, and no trajectory ends close to it.",
    },
    ...(power ? power.checks : []),
  ];
  const files = [
    ["scenario.js", `version ${scenario.version}, id ${scenario.id}`],
    ["power.js", power ? `version ${power.version}, for scenario ${power.scenario_id}` : DATA.power ? "not shown" : "not in this folder"],
    ...(TARGETS.length
      ? [["Targets", `${TARGETS.filter((target) => target.kind === "ground").length} ground, ${TARGETS.filter((target) => target.kind === "satellite").length} satellite`]]
      : []),
    ["3D model", MODEL ? `${MODEL.name}, ${Math.round((MODEL.glb_base64.length * 3) / 4 / 1024)} kB` : "none, so a 1 m cube"],
    ...ARTICULATIONS.map((joint) => [
      "Articulation",
      `${joint.name}: ${joint.part}, about ${joint.axis}` + (joint.park_modes.length ? `, parked in ${joint.park_modes.join(", ")}` : ""),
    ]),
  ];
  // Filled in if the model turns out to be unreadable, once it is decoded
  const modelNote = element("p", { class: "note", style: "display: none" });
  modelScene.then(() => {
    if (!modelProblem) return;
    modelNote.textContent = `${modelProblem}. The body is a 1 m cube instead.`;
    modelNote.style.display = "";
  });

  $("#results").append(
    element(
      "div",
      { class: "cards wide" },
      cards.map(([label, value, unit]) =>
        element("div", { class: "card" }, [element("div", { class: "label", text: label }), element("div", { class: "value" }, [String(value), element("small", { text: unit })])]),
      ),
    ),
    block(
      ["Scenario"],
      [
        kv([
          ["Start, UTC", utcText(0)],
          ["End, UTC", utcText(T_END)],
          ["Length", `${clockText(T_END)}, ${numberText(T_END / PERIOD, 2)} orbits`],
          ["Time step", `${numberText(STEP)} s, ${N} steps`],
          ["Nodal period", `${numberText(PERIOD / 60)} min`],
          ["Beta", `${betaLow.toFixed(2)}° to ${betaHigh.toFixed(2)}°`],
          ["Altitude", `${altLow.toFixed(1)} to ${altHigh.toFixed(1)} km`],
          ["Eclipses", `${eclipses.length}, ${full.length} of them whole`],
          ["Longest whole eclipse", full.length ? clockText(longest) : "none"],
          ["Eclipse fraction", `${(100 * dark / span).toFixed(2)} %, over ${whole ? `${whole} whole orbits` : "the run"}`],
        ]),
        element("p", { class: "note", text: activitySummary() }),
      ],
    ),
    block(
      ["Checks"],
      checks.map((check) =>
        element("div", { class: `check ${check.status}` }, [element("div", { class: "head", text: check.name }), element("div", { class: "detail", text: check.detail })]),
      ),
    ),
    ...(power
      ? [block(["Power"], [kv(power.summary.filter((item) => !item.headline).map((item) => [item.label, `${item.value} ${item.unit}`.trim()]))])]
      : []),
    block(
      ["Files"],
      [
        kv(files),
        modelNote,
        ...(powerNote ? [element("p", { class: "note", text: `The power is not shown: ${powerNote}` })] : []),
        element("p", { class: "note", text: "3D: three.js (MIT). Charts: uPlot (MIT). Coastlines: Natural Earth (public domain). Orbit: SGP4 or a trajectory file, with astropy." }),
      ],
    ),
  );
}
