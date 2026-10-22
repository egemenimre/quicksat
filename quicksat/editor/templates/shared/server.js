// quicksat editor: the editor's local server, as the page sees it.
//
// A page that the server sends holds `DATA.server`: the start of its addresses,
// and the server's key, which each address ends with. The page asks the server
// every few seconds whether it still answers, and every 10 min while it is out
// of view, so that the server knows that a page is open. A page opened from a
// file has no server. Stop the server, in the header, stops it when the user is
// done. The page hears of each change through `page.serverChanged`.

/** The server, as the page last found it. */
const server = {
  /** `none` on a page opened from a file, `up` while the server answers, `down` once it has stopped, `moved` once it has a new key. */
  state: "none",
};

/** The server's address for a name, such as `status`, with the key at its end. */
const serverUrl = (name) => `${DATA.server.base}${name}?key=${DATA.server.key}`;

/** Ask the server whether it still answers, and tell the page if that changed. */
async function checkServer() {
  if (!DATA.server || page.serverBusy()) return;
  let now = "down";
  try {
    const response = await fetch(serverUrl("status"), { cache: "no-store" });
    if (response.ok) {
      now = "up";
      page.onStatus(await response.json());
    } else if (response.status === 404) now = "moved";
  } catch {
    now = "down";
  }
  setServer(now);
}

/** Note the server's state, and tell the page, if it changed. */
function setServer(now) {
  if (now === server.state) return;
  server.state = now;
  $("#stop-server").hidden = now !== "up";
  page.serverChanged();
}

/** Stop the server, after a confirm. The page stays open, with how to start the server again. */
async function stopServer() {
  if (server.state !== "up") return;
  const lost = unsaved() ? " Some changes on this page are not saved yet. After the stop, you can still download them from the Files tab." : "";
  if (!confirm(`Stop the editor's server? This page stays open, but it can no longer use quicksat or save into the folder.${lost}`)) return;
  let result;
  try {
    const response = await fetch(serverUrl("stop"), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    result = await response.json();
  } catch {
    // no answer: the server may have stopped already
    checkServer();
    return;
  }
  if (result.ok) setServer("down");
  else alert(result.error);
}

/** Start asking the server, on a page that it sent. The frame's `startPage` calls this first. */
function startServer() {
  if (!DATA.server) return;
  server.state = "up";
  // every few seconds in view, and every 10 min out of it: the server stops by
  // itself once no page has asked for `DATA.server.idle_h`
  setInterval(() => document.visibilityState === "visible" && checkServer(), 4000);
  setInterval(() => document.visibilityState !== "visible" && checkServer(), 600000);
  window.addEventListener("focus", checkServer);
  $("#stop-server").addEventListener("click", stopServer);
  $("#stop-server").hidden = false;
}
