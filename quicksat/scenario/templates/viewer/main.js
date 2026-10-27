// ---------------------------------------------------------------- Pages and controls

/** The pages with the time controls and the charts. */
const TIMED_PAGES = ["scenario", "power", "attitude", "targets"];

function showPage(page) {
  state.page = page;
  // The Scenario, Power, Attitude and Targets pages share the time controls
  if (TIMED_PAGES.includes(page)) $(`#page-${page}`).append($(".controls"));
  for (const button of $("#page-tabs").querySelectorAll("button")) button.classList.toggle("active", button.dataset.page === page);
  for (const section of document.querySelectorAll(".page")) section.classList.toggle("active", section.id === `page-${page}`);
  markAll();
}

function setPlaying(on) {
  state.playing = on;
  $("#play").innerHTML = on ? "&#10074;&#10074;" : "&#9654;";
}

function setupControls() {
  $("#page-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-page]");
    if (button) showPage(button.dataset.page);
  });
  const speed = $("#speed");
  for (const value of SPEEDS) speed.append(element("option", { value, text: `${value}x` }));
  speed.value = state.speed;
  speed.addEventListener("change", () => (state.speed = Number(speed.value)));
  $("#play").addEventListener("click", () => {
    if (!state.playing && state.t >= T_END) setTime(0);
    setPlaying(!state.playing);
  });
  $("#reset").addEventListener("click", () => {
    setPlaying(false);
    setTime(0);
  });
  $("#slider").addEventListener("input", (event) => setTime(T[Number(event.target.value)]));
  document.addEventListener("keydown", (event) => {
    if (event.target.closest("input:not([type=range]), select, textarea")) return;
    if (event.key === " ") {
      event.preventDefault();
      $("#play").click();
    } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const forward = event.key === "ArrowRight";
      if (event.shiftKey) setTime(state.t + (forward ? 60 : -60));
      else setTime(T[clamp(indexAt(state.t) + (forward ? 1 : -1), 0, N - 1)]);
    } else if (event.key === "Home") {
      $("#reset").click();
    }
  });

  const shown = power ? "with power" : DATA.power ? "power not shown" : "scenario only";
  $("#subtitle").replaceChildren(
    element("b", { text: SCENARIO_FILE }),
    ` · ${shown} · ${utcText(0)} UTC · ${clockText(T_END)} at ${numberText(STEP)} s`,
  );
  if (powerNote) $("#subtitle").title = powerNote;
  document.title = `quicksat Scenario Viewer · ${SCENARIO_FILE}`;
}

function observe(selector, resize) {
  const node = $(selector);
  new ResizeObserver(() => {
    if (node.clientWidth > 0 && node.clientHeight > 0) {
      resize(node.clientWidth, node.clientHeight);
      markAll();
    }
  }).observe(node);
}

// ---------------------------------------------------------------- Start

setupControls();
// the designer has only the Scenario page, with no 3D views
if (!DESIGNER) {
  showActivities();
  showAttitude();
  showInputs();
  showTargets();
  showResults();
  showPowerSetup();
  showThermal();
}
trackColours.start();
observe("#vp-orbit", (w, h) => orbitView.resize(w, h));
if (!DESIGNER) observe("#vp-body", (w, h) => bodyView.resize(w, h));
observe("#vp-ground", (w, h) => groundView.resize(w, h));
// The designer's view carries over from the run before, in the address's hash
const startView = DESIGNER ? viewFromHash(location.hash) : { t: null, zoom: null };
if (startView.zoom) charts.show(...startView.zoom);
setTime(startView.t ?? 0);
if (DESIGNER) {
  // the editor selects an activity when its row is selected in the list
  window.addEventListener("message", (event) => {
    const message = event.data;
    if (event.origin !== location.origin || event.source !== window.parent) return;
    if (!message || message.source !== "quicksat-designer") return;
    if (message.type === "select") select(Number.isInteger(message.number) ? message.number : null);
  });
  tellEditor("ready");
}

let last = performance.now();
function frame(now) {
  const elapsed = Math.min((now - last) / 1000, 0.25);
  last = now;
  if (state.playing) {
    let next = state.t + elapsed * state.speed;
    if (next >= T_END) {
      next = T_END;
      setPlaying(false);
    }
    setTime(next);
  }
  if (dirty.charts && TIMED_PAGES.includes(state.page)) {
    charts.redraw();
    dirty.charts = false;
  }
  if (state.page === "scenario") {
    // the designer can hide the orbit, and then it is not drawn
    if (dirty.orbit && !document.body.classList.contains("no-orbit")) {
      orbitView.update();
      orbitView.render();
      dirty.orbit = false;
    }
    if (dirty.body && bodyView) {
      bodyView.update();
      bodyView.render();
      dirty.body = false;
    }
    if (dirty.ground) {
      groundView.render();
      dirty.ground = false;
    }
  }
  if (dirty.readouts) {
    readouts();
    dirty.readouts = false;
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
