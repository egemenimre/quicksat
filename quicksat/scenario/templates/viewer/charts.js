// ---------------------------------------------------------------- Charts

const charts = (() => {
  // the designer hides the power charts in its own layout
  if (!power && !DESIGNER) $("#charts").classList.add("no-power");
  const eclipses = ECLIPSES;
  const AXIS_SIZE = 96; // the same on every chart, so that their plots line up
  const list = [];
  let syncing = false;
  const px = () => uPlot.pxRatio;

  const axis = {
    stroke: THEME.muted,
    font: `10.5px ${MONO}`,
    labelFont: `10.5px ${MONO}`,
    grid: { stroke: THEME.grid, width: 1 },
    ticks: { stroke: THEME.tick, width: 1, size: 4 },
  };
  const hiddenX = { ...axis, size: 4, values: (u, ticks) => ticks.map(() => "") };
  const shownX = { ...axis, size: 24, values: (u, ticks) => ticks.map((m) => `${m}m`) };

  function clipped(u, draw) {
    const c = u.ctx;
    const box = u.bbox;
    c.save();
    c.beginPath();
    c.rect(box.left, box.top, box.width, box.height);
    c.clip();
    draw(c, box);
    c.restore();
  }

  const shadeEclipses = (u) =>
    clipped(u, (c, box) => {
      c.fillStyle = THEME.eclipseBand;
      for (const piece of eclipses) {
        const x0 = u.valToPos(piece.start_s / 60, "x", true);
        c.fillRect(x0, box.top, u.valToPos(piece.end_s / 60, "x", true) - x0, box.height);
      }
    });

  // Each row's bars, with their value on them where it fits, as in the
  // notebook's Gantt chart. A box over all the rows marks an occurrence
  // outside its constraint, and a dashed one an event that never came. A
  // dashed red line marks an occurrence with a negative duration.
  const drawTracks = (u) =>
    clipped(u, (c, box) => {
      const rowHeight = box.height / ROWS.length;
      const right = box.left + box.width;
      c.font = `${10 * px()}px ${MONO}`;
      c.textAlign = "center";
      c.textBaseline = "middle";
      ROWS.forEach(([key], row) => {
        const top = box.top + (row + 0.14) * rowHeight;
        const height = 0.72 * rowHeight;
        for (const piece of TRACKS[key]) {
          const x0 = u.valToPos(piece.start_s / 60, "x", true);
          const x1 = u.valToPos(piece.end_s / 60, "x", true);
          if (x1 < box.left || x0 > right) continue;
          const fill = colourOf(piece.value);
          c.fillStyle = fill;
          c.fillRect(x0, top, Math.max(px(), x1 - x0 - px()), height);
          const left = Math.max(x0, box.left);
          const end = Math.min(x1, right);
          const text = pieceText(piece);
          if (end - left > c.measureText(text).width + 8 * px()) {
            c.fillStyle = textOn(fill);
            c.fillText(text, (left + end) / 2, top + height / 2);
          }
        }
      });
      for (const occurrence of OCCURRENCES) {
        const outside = occurrence.statuses.includes("outside constraint");
        const neverCame = occurrence.statuses.includes("event never came");
        if (!outside && !neverCame) continue;
        const x0 = u.valToPos(occurrence.start_s / 60, "x", true);
        const x1 = u.valToPos(occurrence.end_s / 60, "x", true);
        c.strokeStyle = outside ? THEME.critical : THEME.warning;
        c.lineWidth = 2 * px();
        c.setLineDash(outside ? [] : [5 * px(), 3 * px()]);
        c.strokeRect(x0 + px(), box.top + px(), x1 - x0 - 2 * px(), box.height - 2 * px());
      }
      // In the designer, a box in the accent colour marks each occurrence of
      // the activity selected in the list
      if (state.selected !== null) {
        c.strokeStyle = THEME.accent;
        c.lineWidth = 2 * px();
        c.setLineDash([]);
        for (const occurrence of occurrencesOf(OCCURRENCES, state.selected)) {
          const x0 = u.valToPos(occurrence.start_s / 60, "x", true);
          const x1 = u.valToPos(occurrence.end_s / 60, "x", true);
          c.strokeRect(x0 + px(), box.top + px(), x1 - x0 - 2 * px(), box.height - 2 * px());
        }
      }
      // A negative duration takes no time, so it is a dashed line at its
      // start, with a triangle on top, as in the notebook
      c.strokeStyle = c.fillStyle = THEME.critical;
      c.lineWidth = 2 * px();
      c.setLineDash([5 * px(), 3 * px()]);
      for (const occurrence of OCCURRENCES) {
        if (!occurrence.statuses.includes("negative duration")) continue;
        const x = u.valToPos(occurrence.start_s / 60, "x", true);
        c.beginPath();
        c.moveTo(x, box.top);
        c.lineTo(x, box.top + box.height);
        c.stroke();
        c.beginPath();
        c.moveTo(x - 5 * px(), box.top);
        c.lineTo(x + 5 * px(), box.top);
        c.lineTo(x, box.top + 8 * px());
        c.fill();
      }
      c.setLineDash([]);
    });

  // A thin line at each whole orbit from the start. On a timeline, each label
  // sits in a strip above the rows, where it covers no bar, if there is room
  // for it between the marks.
  const MARKS = orbitMarks(PERIOD, T_END);
  const LABEL_STRIP = 13; // CSS pixels
  const markOrbits = (labelled) => (u) => {
    const at = (mark) => Math.round(u.valToPos(mark.time_s / 60, "x", true)) + 0.5;
    clipped(u, (c, box) => {
      c.strokeStyle = "rgba(205, 217, 234, 0.55)";
      c.lineWidth = px();
      c.setLineDash([3 * px(), 3 * px()]);
      for (const mark of MARKS) {
        c.beginPath();
        c.moveTo(at(mark), box.top);
        c.lineTo(at(mark), box.top + box.height);
        c.stroke();
      }
      c.setLineDash([]);
    });
    if (!labelled) return;
    const c = u.ctx;
    const box = u.bbox;
    c.save();
    c.beginPath();
    c.rect(box.left, 0, box.width, box.top);
    c.clip();
    c.font = `${9.5 * px()}px ${MONO}`;
    c.fillStyle = THEME.muted;
    c.textAlign = "left";
    c.textBaseline = "bottom";
    const spacing = MARKS.length > 1 ? at(MARKS[1]) - at(MARKS[0]) : Infinity;
    for (const mark of MARKS) {
      if (c.measureText(mark.label).width + 10 * px() > spacing) break;
      c.fillText(mark.label, at(mark) + 3 * px(), box.top - 1.5 * px());
    }
    c.restore();
  };

  // Where the rate or the acceleration passes the slew block's limit: an amber
  // band, under the lines of the Attitude page's charts and over the bars of
  // the designer's timeline
  const shadeExcesses = (u) =>
    clipped(u, (c, box) => {
      c.fillStyle = THEME.excessBand;
      for (const piece of EXCESSES) {
        const x0 = u.valToPos(piece.start_s / 60, "x", true);
        c.fillRect(x0, box.top, Math.max(u.valToPos(piece.end_s / 60, "x", true) - x0, 1), box.height);
      }
    });

  const cursorLine = (u) =>
    clipped(u, (c, box) => {
      const x = u.valToPos(state.t / 60, "x", true);
      c.strokeStyle = "#ffffff";
      c.lineWidth = 1.5 * px();
      c.beginPath();
      c.moveTo(x, box.top);
      c.lineTo(x, box.top + box.height);
      c.stroke();
    });

  function make(target, options, data) {
    const host = $(target);
    const chart = new uPlot(
      {
        width: Math.max(host.clientWidth, 300),
        height: Math.max(host.clientHeight, 40),
        legend: { show: false },
        // a fixed top padding leaves room for labels above the plot, and null keeps the rest automatic
        ...(options.padding ? { padding: options.padding } : {}),
        cursor: { sync: { key: "scenario" }, drag: { x: true, y: false }, y: false, points: { show: false } },
        scales: { x: { time: false }, y: { range: options.range } },
        axes: [options.xAxis, { ...axis, size: AXIS_SIZE, ...options.yAxis }],
        series: [{}, ...options.series.map((s) => ({ width: 1.6, points: { show: false }, ...s }))],
        hooks: {
          drawClear: options.drawClear ? [options.drawClear] : [],
          draw: [...(options.draw ? [options.draw] : []), cursorLine],
          setScale: [
            (u, key) => {
              if (key !== "x" || syncing) return;
              syncing = true;
              for (const other of list) if (other !== u) other.setScale("x", { min: u.scales.x.min, max: u.scales.x.max });
              syncing = false;
              reportView();
            },
          ],
        },
      },
      [MINUTES, ...data],
      host,
    );
    // A click that is not a drag moves the time cursor
    let downAt = null;
    chart.over.addEventListener("mousedown", (event) => (downAt = event.clientX));
    chart.over.addEventListener("mouseup", (event) => {
      if (downAt !== null && Math.abs(event.clientX - downAt) < 3) {
        const time = chart.posToVal(event.offsetX, "x") * 60;
        if (DESIGNER) pick(time);
        else setTime(time);
      }
      downAt = null;
    });
    new ResizeObserver(() => {
      if (host.clientWidth > 0 && host.clientHeight > 0) chart.setSize({ width: host.clientWidth, height: host.clientHeight });
    }).observe(host);
    list.push(chart);
    return chart;
  }

  function head(target, title, unit, keys, help) {
    const values = keys.map(() => element("b"));
    $(target).replaceChildren(
      element("span", { class: "title", text: title, "data-help": help }),
      element("span", { class: "unit", text: unit }),
      ...keys.map(([label, colour], k) =>
        element("span", { class: "key" }, [element("span", { class: "swatch", style: `background:${colour}` }), `${label} `, values[k]]),
      ),
    );
    return values;
  }

  // The Gantt chart, with one row for each track. The Scenario page has one,
  // and the Power page another. Each has the orbit marks, and the designer's
  // has the turn rate bands over its bars.
  function gantt(target, xAxis, overlays = []) {
    const chart = make(
      target,
      {
        range: () => [0, ROWS.length],
        xAxis,
        yAxis: {
          grid: { show: false },
          ticks: { show: false },
          splits: () => ROWS.map((_, row) => ROWS.length - row - 0.5),
          values: (u, splits) => splits.map((s) => ROWS[Math.round(ROWS.length - 0.5 - s)][1]),
        },
        series: [{ stroke: "transparent" }],
        padding: [LABEL_STRIP, null, null, null],
        draw: (u) => [drawTracks, ...overlays, markOrbits(true)].forEach((draw) => draw(u)),
      },
      [MINUTES.map(() => null)],
    );
    chart.over.addEventListener("mousemove", (event) => {
      const time = chart.posToVal(event.offsetX, "x") * 60;
      const row = clamp(Math.floor((event.offsetY / chart.over.clientHeight) * ROWS.length), 0, ROWS.length - 1);
      const piece = pieceAt(TRACKS[ROWS[row][0]], time);
      const occurrence = activityAt(time);
      chart.over.title =
        `${pieceText(piece)}: ${clockText(piece.start_s)} to ${clockText(piece.end_s)}\n` +
        (occurrence
          ? `Activity ${occurrence.number} of repeat ${occurrence.repeat}${occurrence.title ? `, ${occurrence.title}` : ""}: ` +
            `until ${occurrence.trigger} · ${occurrence.statuses.join(", ")}`
          : "Unplanned: no activity, after the last one");
    });
    return chart;
  }
  // The designer's timeline has each target's passes under it, with the time axis
  const lanesBelow = DESIGNER && TARGETS.length;
  gantt("#chart-gantt", power || lanesBelow ? hiddenX : shownX, DESIGNER ? [shadeExcesses] : []);

  // Round a chart's range out to the next 50 W, with some room
  const roundOut = (value) => (value >= 0 ? Math.ceil((value * 1.1) / 50) * 50 : Math.floor((value * 1.1) / 50) * 50);

  const values = {};
  if (power) {
    const grid = power.grid;

    // The Scenario page: the net power, which is the generated less the
    // consumed, above the battery's charge. The surplus and the deficit are
    // two series, so that each fills to zero in its own colour.
    const net = NET_W;
    const netLow = roundOut(Math.min(0, ...net));
    const netHigh = roundOut(Math.max(0, ...net)) || 50;
    make(
      "#chart-net",
      {
        range: () => [netLow, netHigh],
        xAxis: hiddenX,
        yAxis: {},
        series: [
          { stroke: THEME.generated, fill: THEME.generatedFill, fillTo: 0 },
          { stroke: THEME.consumed, fill: THEME.consumedFill, fillTo: 0 },
        ],
        drawClear: shadeEclipses,
      },
      [net.map((value) => Math.max(value, 0)), net.map((value) => Math.min(value, 0))],
    );
    [values.net] = head("#head-net", "NET POWER", "W", [["Generated less consumed", THEME.netSwatch]], "net");

    // The battery's charge, at the foot of both pages. Its title gives the
    // charge at the time cursor on the Scenario page. The Power page has its
    // current power panel for that.
    const soc = grid.soc.map((value) => 100 * value);
    const floor = 100 * (1 - power.battery.max_depth_of_discharge);
    const lowest = Math.floor(Math.min(floor, ...soc) - 5);
    function battery(target, headTarget) {
      make(
        target,
        {
          range: () => [lowest, 102],
          xAxis: shownX,
          yAxis: {},
          series: [
            { stroke: THEME.soc, fill: THEME.socFill },
            { stroke: THEME.limit, dash: [6, 4], width: 1.2 },
          ],
          drawClear: shadeEclipses,
        },
        [soc, soc.map(() => floor)],
      );
      const [socValue, limitValue] = head(headTarget, "BATTERY", "%", [["State of charge", THEME.soc], ["Limit", THEME.limit]], "battery");
      limitValue.textContent = `${numberText(floor)} %`;
      return socValue;
    }
    values.soc = battery("#chart-soc", "#head-soc");

    // The Power page: the timeline, the detailed power chart under it, and
    // the battery's charge at the foot. Each line has a button that shows or
    // hides it. The totals start shown, and the panels hidden.
    $("#page-tabs").querySelector('[data-page="power"]').hidden = false;
    gantt("#power-gantt", hiddenX);
    const lines = [
      { label: "Generated", data: grid.generated_w, shown: true, help: "generated", series: { stroke: THEME.generated, fill: THEME.generatedFill } },
      { label: "Consumed", data: grid.consumed_w, shown: true, help: "consumed", series: { stroke: THEME.consumed, paths: uPlot.paths.stepped({ align: 1 }) } },
      ...grid.panel_w.map((data, j) => ({
        label: PANELS[j].name,
        data,
        shown: false,
        help: "panelPower",
        series: { stroke: panelColour(j), width: 1.3 },
      })),
    ];
    const detail = make(
      "#chart-detail",
      {
        range: (u, lo, hi) => [0, roundOut(hi || 1)],
        xAxis: hiddenX,
        yAxis: {},
        series: lines.map((line) => ({ ...line.series, show: line.shown })),
        drawClear: shadeEclipses,
      },
      lines.map((line) => line.data),
    );
    lines.forEach((line, j) => {
      const button = element("button", { class: `toggle series${line.shown ? " on" : ""}`, "data-help": line.help }, [
        element("span", { class: "swatch", style: `background:${line.series.stroke}` }),
        line.label,
      ]);
      button.addEventListener("click", () => {
        const shown = !button.classList.contains("on");
        button.classList.toggle("on", shown);
        detail.setSeries(j + 1, { show: shown });
      });
      line.button = button;
    });
    $("#head-detail").replaceChildren(
      element("span", { class: "title", text: "POWER", "data-help": "power" }),
      element("span", { class: "unit", text: "W" }),
      ...lines.map((line) => line.button),
    );
    battery("#chart-soc-detail", "#head-soc-detail");
  }

  // The Attitude page: the timeline, the roll, pitch and yaw against LVLH,
  // the body rate and its acceleration. Where the rate or the acceleration
  // passes the slew block's limit, an amber band crosses all three charts. The
  // designer has no Attitude page.
  if (!DESIGNER) {
    gantt("#attitude-gantt", hiddenX);
    // a jump across ±180 deg is a wrap, not a turn: leave a gap there
    const unwrapped = (values) => values.map((value, k) => (k > 0 && Math.abs(value - values[k - 1]) > 180 ? null : value));
    const angles = [
      ["Roll", ATTITUDE.roll_deg, AXIS_COLOURS[0]],
      ["Pitch", ATTITUDE.pitch_deg, AXIS_COLOURS[1]],
      ["Yaw", ATTITUDE.yaw_deg, AXIS_COLOURS[2]],
    ];
    make(
      "#chart-angles",
      {
        range: () => [-180, 180],
        xAxis: hiddenX,
        yAxis: { splits: () => [-180, -90, 0, 90, 180] },
        series: angles.map(([, , colour]) => ({ stroke: colour, width: 1.3 })),
        drawClear: shadeExcesses,
      },
      angles.map(([, values]) => unwrapped(values)),
    );
    head("#head-angles", "ROLL, PITCH, YAW", "deg, against LVLH", angles.map(([label, , colour]) => [label, colour]), "attitudeAngles").forEach(
      (value) => value.remove(),
    );
    // the rate and the acceleration, each with its limit as a dashed line
    function rateChart(target, headTarget, title, unit, values, limit, help, last) {
      const top = Math.max(limit || 0, ...values.filter((v) => v !== null)) * 1.15 || 1;
      make(
        target,
        {
          range: () => [0, top],
          xAxis: last ? shownX : hiddenX,
          yAxis: {},
          series: [
            { stroke: THEME.accent, fill: THEME.socFill, paths: uPlot.paths.stepped({ align: 1 }) },
            { stroke: THEME.limit, dash: [6, 4], width: 1.2 },
          ],
          drawClear: shadeExcesses,
        },
        [values, values.map(() => limit)],
      );
      const keys = [["Body", THEME.accent], ...(limit === null ? [] : [["Slew limit", THEME.limit]])];
      const [bodyValue, limitValue] = head(headTarget, title, unit, keys, help);
      bodyValue.remove();
      if (limitValue) limitValue.textContent = `${numberText(limit, 4)} ${unit}`;
    }
    rateChart("#chart-rate", "#head-rate", "BODY RATE", "deg/s", ATTITUDE.rate_deg_s, ATTITUDE.max_rate_deg_s, "bodyRate", false);
    rateChart(
      "#chart-acceleration", "#head-acceleration", "ACCELERATION", "deg/s²",
      ATTITUDE.acceleration_deg_s2, ATTITUDE.max_acceleration_deg_s2, "bodyAcceleration", true,
    );
  }

  // The Targets page: the timeline, and when each target is in view, with a
  // row for each target and a bar for each pass. A thin bar under the passes
  // shows when the body or a part points at the target, in view or not. The
  // designer has the lanes under its own timeline, and no Targets page.
  if (TARGETS.length) {
    if (!DESIGNER) {
      $("#page-tabs").querySelector('[data-page="targets"]').hidden = false;
      gantt("#targets-gantt", hiddenX);
    }
    const rows = TARGETS.length;
    const drawLanes = (u) =>
      clipped(u, (c, box) => {
        const rowHeight = box.height / rows;
        const bar = (span, top, height) => {
          const x0 = u.valToPos(span.start_s / 60, "x", true);
          const x1 = u.valToPos(span.end_s / 60, "x", true);
          c.fillRect(x0, top, Math.max(px(), x1 - x0), height);
        };
        TARGETS.forEach((target, row) => {
          const top = box.top + (row + 0.12) * rowHeight;
          c.fillStyle = targetColour(target);
          for (const pass of target.passes) bar(pass, top, 0.5 * rowHeight);
          c.fillStyle = THEME.text;
          const strip = Math.max(2 * px(), 0.12 * rowHeight);
          for (const span of POINTED[target.name] || []) bar(span, top + 0.62 * rowHeight, strip);
        });
      });
    const lanes = make(
      "#chart-lanes",
      {
        range: () => [0, rows],
        xAxis: shownX,
        yAxis: {
          grid: { show: false },
          ticks: { show: false },
          splits: () => TARGETS.map((_, row) => rows - row - 0.5),
          values: (u, splits) => splits.map((s) => TARGETS[Math.round(rows - 0.5 - s)].name),
        },
        series: [{ stroke: "transparent" }],
        draw: (u) => [drawLanes, ...(DESIGNER ? [shadeExcesses] : []), markOrbits(false)].forEach((draw) => draw(u)),
      },
      [MINUTES.map(() => null)],
    );
    lanes.over.addEventListener("mousemove", (event) => {
      const time = lanes.posToVal(event.offsetX, "x") * 60;
      const row = clamp(Math.floor((event.offsetY / lanes.over.clientHeight) * rows), 0, rows - 1);
      const target = TARGETS[row];
      const pass = passAt(target.passes, time, T_END);
      const pointed = passAt(POINTED[target.name] || [], time, T_END);
      lanes.over.title = [
        pass
          ? `${target.name}: in view from ${clockText(pass.start_s)} to ${clockText(pass.end_s)}, ${numberText((pass.end_s - pass.start_s) / 60, 2)} min`
          : `${target.name}: out of view`,
        ...(pointed ? [`pointed at from ${clockText(pointed.start_s)} to ${clockText(pointed.end_s)}`] : []),
      ].join("\n");
    });
    const kinds = ["ground", "satellite"].filter((kind) => TARGETS.some((target) => target.kind === kind));
    const keys = [...kinds.map((kind) => [kind, TARGET_COLOURS[kind][0]]), ["pointed at", THEME.text]];
    head("#head-lanes", "IN VIEW", "each target's passes", keys, "lanes");
  }

  function zoom(from, to) {
    list[0].setScale("x", { min: clamp(from, 0, T_END / 60), max: clamp(to, 0, T_END / 60) });
  }
  const now = () => state.t / 60;
  const zooms = [
    ["Full", () => zoom(0, T_END / 60), "zoomFull"],
    ["1 orbit", () => zoom(now() - PERIOD / 120, now() + PERIOD / 120), "zoomOrbit"],
    ["30 min", () => zoom(now() - 15, now() + 15), "zoom30"],
  ];
  const zoomBars = DESIGNER ? ["#zooms"] : ["#zooms", ...(power ? ["#power-zooms"] : []), "#attitude-zooms"];
  for (const target of [...zoomBars, ...(TARGETS.length && !DESIGNER ? ["#targets-zooms"] : [])]) {
    for (const [label, action, help] of zooms) {
      $(target).append(element("button", { class: "toggle", text: label, onclick: action, "data-help": help }));
    }
  }

  // With power, a button that puts the charts across the full width, under the
  // views. The browser remembers the choice, where it can.
  if (power) {
    const page = $("#page-scenario");
    const button = element("button", { class: "toggle layout", text: "Wide", "data-help": "wide" });
    const setWide = (on) => {
      page.classList.toggle("wide", on);
      button.classList.toggle("on", on);
    };
    let stored = false;
    try {
      stored = localStorage.getItem("quicksat-viewer-wide") === "1";
    } catch {
      // No storage, as in some private windows: start narrow
    }
    setWide(stored);
    button.addEventListener("click", () => {
      const on = !page.classList.contains("wide");
      setWide(on);
      try {
        localStorage.setItem("quicksat-viewer-wide", on ? "1" : "0");
      } catch {
        // The choice then lasts until the page is closed
      }
    });
    $("#zooms").append(button);
  }

  return {
    redraw() {
      for (const chart of list) chart.redraw(false, false);
    },
    /** The time that the charts show, from and to, in seconds. */
    shown() {
      const x = list[0].scales.x;
      return [x.min * 60, x.max * 60];
    },
    /** Show the time from one second to another on the charts. */
    show(from, to) {
      zoom(from / 60, to / 60);
    },
    values,
  };
})();
