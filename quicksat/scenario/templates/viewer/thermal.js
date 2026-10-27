// ---------------------------------------------------------------- The Thermal page

/** One decimal, or a dash where the account has no value. */
const tenths = (value) => (value == null ? "–" : value.toFixed(1));

/** The account's terms, each a mean power positive into the payload, then the net and the ΔT. */
const ACCOUNT_TERMS = [
  ["dissipation [W]", "Dissipation"],
  ["heaters [W]", "Heaters"],
  ["heat flows [W]", "Heat flows"],
  ["sun [W]", "Sun"],
  ["albedo [W]", "Albedo"],
  ["Earth infrared [W]", "Earth IR"],
  ["emitted [W]", "Emitted"],
  ["net [W]", "Net W"],
  ["net [Wh]", "Net W h"],
  ["ΔT [K]", "ΔT K"],
];

/**
 * A table with a row for each entry, and a column for each of `columns`: its
 * key, its title, and how to write its value. A number takes one decimal by
 * default. A net below zero is red, and one above it amber. A row with no ΔT
 * says why on hover.
 */
function accountTable(rows, columns) {
  const text = (value, write) => (write ? write(value) : typeof value === "number" ? tenths(value) : String(value ?? "–"));
  const cell = ([key, , write], k, row) => {
    const value = row[key];
    const tone = key.startsWith("net") && value ? (value < 0 ? " neg" : " pos") : "";
    return element("td", { class: k ? `num${tone}` : "", text: text(value, write) });
  };
  return element("div", { class: "scroll-x" }, [
    element("table", { class: "list account" }, [
      element("thead", {}, [element("tr", {}, columns.map(([, title], k) => element("th", { class: k ? "num" : "", text: title })))]),
      element(
        "tbody",
        {},
        rows.map((row) =>
          element("tr", row["ΔT note"] ? { title: `No ΔT: ${row["ΔT note"]}` } : {}, columns.map((column, k) => cell(column, k, row))),
        ),
      ),
    ]),
  ]);
}

/**
 * The net heat into the payload since the start, in W h, over the payload's
 * modes in their timeline colours. The chart is drawn once its block has a
 * width, since the page starts hidden.
 */
function heatChart(account) {
  const host = element("div", { class: "thermal-plot" });
  const readout = element("b");
  const modes = [...new Set(account.bands.map((band) => band.mode))];
  const axis = {
    stroke: THEME.muted,
    font: `10.5px ${MONO}`,
    labelFont: `10.5px ${MONO}`,
    grid: { stroke: THEME.grid, width: 1 },
    ticks: { stroke: THEME.tick, width: 1, size: 4 },
  };
  const shadeModes = (u) => {
    const c = u.ctx;
    const box = u.bbox;
    c.save();
    c.beginPath();
    c.rect(box.left, box.top, box.width, box.height);
    c.clip();
    c.globalAlpha = 0.22;
    for (const band of account.bands) {
      const x0 = u.valToPos(band.start_min, "x", true);
      c.fillStyle = colourOf(band.mode);
      c.fillRect(x0, box.top, u.valToPos(band.end_min, "x", true) - x0, box.height);
    }
    c.restore();
  };
  const showValue = (u) => {
    const i = u.cursor.idx;
    readout.textContent = i == null ? "" : `${tenths(account.energy_wh[i])} W h at ${numberText(account.t_min[i], 1)} min`;
  };
  let chart = null;
  new ResizeObserver(() => {
    const width = host.clientWidth;
    if (!width) return;
    if (chart) {
      chart.setSize({ width, height: host.clientHeight });
      return;
    }
    chart = new uPlot(
      {
        width,
        height: host.clientHeight,
        legend: { show: false },
        cursor: { drag: { x: true, y: false }, y: false, points: { show: false } },
        scales: { x: { time: false } },
        axes: [
          { ...axis, size: 36, label: "time from the start, min" },
          { ...axis, size: 60, label: "W h" },
        ],
        series: [{}, { stroke: THEME.text, width: 1.6, points: { show: false } }],
        hooks: { drawClear: [shadeModes], setCursor: [showValue] },
      },
      [account.t_min, account.energy_wh],
      host,
    );
  }).observe(host);
  const legend = modes.map((mode) => element("span", {}, [element("span", { class: "swatch", style: `background:${colourOf(mode)}` }), mode]));
  return [element("div", { class: "thermal-head" }, [...legend, readout]), host];
}

/**
 * The Thermal page: the payload's heat account from power.js, as the Scenario
 * Editor's Thermal tab shows it, without its fields and buttons. It shows only
 * when the thermal command or the editor wrote power.js with the account.
 */
function showThermal() {
  const account = power && power.thermal;
  if (!account) return;
  $("#page-tabs").querySelector('[data-page="thermal"]').hidden = false;
  const minutes = ["time [min]", "Min"];
  const whole = (value) => String(value);
  const file = account.file || "the payload's thermal file";
  const blocks = [
    block(
      ["By payload mode"],
      [
        accountTable(account.modes, [
          ["payload mode", "Mode"],
          minutes,
          ...ACCOUNT_TERMS,
          ["balancing heater [W]", "Balancing heater W"],
          ["run balancing heater [W]", "Run balancing heater W"],
        ]),
        element("p", {
          class: "note",
          text:
            "Each term is a mean power over the mode's time in the run, positive into the payload, without margins. " +
            "The ΔT is how far the floating surfaces would move from their design temperatures if the mode went on forever. " +
            "The balancing heater brings the mode's own net energy to zero: the heater to install. " +
            "The run balancing heater brings the run's net energy to zero, in the modes that lose heat only: a thermostat's mean power. " +
            "The heaters column is the heater row of the payload's consumption file. Set it there, or on the Scenario Editor's Thermal tab.",
        }),
      ],
      true,
    ),
    block(
      ["By activity"],
      [
        accountTable(account.activities, [["activity", "Activity"], ["occurrences", "Times", whole], minutes, ...ACCOUNT_TERMS]),
        element("p", { class: "note", text: "Each activity over all its occurrences, with the slew into each." }),
      ],
      true,
    ),
    block(
      ["The net heat in since the start"],
      [
        ...heatChart(account),
        element("p", {
          class: "note",
          text:
            "Where the line rises, heat builds up in the payload. Where it falls, the payload cools. " +
            "The model has no heat capacity, so this is an energy, not a temperature. The bands are the payload's modes.",
        }),
      ],
      true,
    ),
    ...(account.orbits.length
      ? [
          block(
            ["By whole orbit"],
            [
              accountTable(account.orbits, [
                ["orbit", "Orbit", whole],
                ["start [UTC]", "From, UTC", (value) => value.replace("T", " ").slice(0, 19)],
                ...ACCOUNT_TERMS,
              ]),
              element("p", { class: "note", text: "One row for each whole orbit, counted from the start of the run, as the power budget counts them." }),
            ],
            true,
          ),
        ]
      : []),
    block(
      ["The surfaces"],
      [
        accountTable(account.surfaces, [
          ["surface", "Surface"],
          ["area [m2]", "Area m²", (value) => value.toFixed(3)],
          ["absorptance", "Absorptance", (value) => value.toFixed(2)],
          ["emissivity", "Emissivity", (value) => value.toFixed(2)],
          ["temperature [K]", "Design K"],
          ["fixed", "Temperature", (value) => (value ? "fixed" : "floating")],
          ["lowest sun angle [deg]", "Sun angle from"],
          ["highest sun angle [deg]", "To, deg"],
          ["in sun [min]", "In sun, min"],
          ["peak sun [W]", "Peak sun W"],
          ["mean sun [W]", "Mean sun W"],
          ["mean view factor", "View factor", (value) => value.toFixed(3)],
          ["mean albedo [W]", "Albedo W"],
          ["mean Earth infrared [W]", "Earth IR W"],
          ["emitted [W]", "Emitted W"],
        ]),
        element("p", {
          class: "note",
          text:
            "Each surface's properties, the sun's angle to its normal outside the umbra, the time it sees the sun, " +
            "and its mean heat over the run. Each surface emits at its design temperature.",
        }),
      ],
      true,
    ),
    block(
      ["Notes"],
      [
        ...account.notes.map((text) => element("p", { class: "note", text })),
        element("p", { class: "note", text: `From ${file}. The file itself is on the Inputs tab.` }),
      ],
      true,
    ),
  ];
  $("#thermal").replaceChildren(...blocks);
}
