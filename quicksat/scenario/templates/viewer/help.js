// ---------------------------------------------------------------- Explanations

/** What each window, value and button is, for the box that appears on hover: help.yaml. */
const HELP = JSON.parse($("#help").textContent);

/**
 * The box that explains whatever the pointer rests on. It appears after a
 * moment, below the element, or above it when there is no room below.
 */
(function explanations() {
  const box = element("div", { class: "help", hidden: "" });
  document.body.append(box);
  let target = null;
  let timer = null;

  function hide() {
    clearTimeout(timer);
    box.hidden = true;
  }

  function show(node) {
    const help = HELP[node.dataset.help];
    if (!help) return;
    box.replaceChildren(element("b", { text: help.title }), help.text);
    box.hidden = false;
    const rect = node.getBoundingClientRect();
    const left = Math.min(rect.left, innerWidth - 8 - box.offsetWidth);
    const below = rect.bottom + 6;
    const top = below + box.offsetHeight > innerHeight - 8 ? rect.top - 6 - box.offsetHeight : below;
    box.style.left = `${Math.max(8, left)}px`;
    box.style.top = `${Math.max(8, top)}px`;
  }

  document.addEventListener("pointerover", (event) => {
    const node = event.target.closest("[data-help]");
    if (node === target) return;
    target = node;
    hide();
    if (node) timer = setTimeout(() => show(node), 250);
  });
  document.addEventListener("pointerout", (event) => {
    if (!event.relatedTarget) {
      target = null;
      hide();
    }
  });
  // A click on a button or a view hides the box. A tap on a touch screen
  // shows it, and the next tap elsewhere hides it.
  document.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse") hide();
  });
  document.addEventListener("scroll", hide, true);
})();
