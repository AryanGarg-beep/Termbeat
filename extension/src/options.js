// Add and remove the user's own stations (storage.sync). Validation is the
// terminal app's add-station form, ported in common.js.

import {
  loadStations, loadCustomStations, saveCustomStations, stationEntry, stationProblem, originPattern,
} from "./common.js";

const api = globalThis.browser ?? globalThis.chrome;
const $ = (id) => document.getElementById(id);

async function renderList() {
  const custom = await loadCustomStations();
  $("empty").hidden = custom.length > 0;
  $("list").replaceChildren(...custom.map((s, i) => {
    const li = document.createElement("li");
    const name = Object.assign(document.createElement("span"), { className: "name", textContent: s.station });
    const url = Object.assign(document.createElement("span"), { className: "url", textContent: s.url, title: s.url });
    const del = Object.assign(document.createElement("button"), { textContent: "Remove" });
    del.setAttribute("aria-label", `Remove ${s.station}`);
    del.onclick = async () => {
      const list = await loadCustomStations();
      list.splice(i, 1);
      await saveCustomStations(list);
      renderList();
    };
    li.append(name, url, del);
    return li;
  }));
}

$("add").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("error").textContent = "";
  $("saved").textContent = "";
  const fields = {
    name: $("name").value, url: $("url").value, freq: $("freq").value,
    genre: $("genre").value, bitrate: $("bitrate").value,
  };
  // The basic checks need no storage, so the permission prompt below can be
  // the first await: Firefox only allows it directly inside the user's click.
  const early = stationProblem(fields, []);
  if (early) { $("error").textContent = early; return; }

  // The stream's site: optional. Without it the station plays, with a
  // simulated spectrum and no now-playing titles.
  try {
    await api.permissions.request({ origins: [originPattern(fields.url.trim())] });
  } catch { /* declined or unsupported */ }

  const all = await loadStations();
  const problem = stationProblem(fields, all);
  if (problem) { $("error").textContent = problem; return; }
  const entry = stationEntry(fields, $("provider").value, all);
  const custom = await loadCustomStations();
  custom.push(entry);
  await saveCustomStations(custom);
  $("add").reset();
  $("saved").textContent = `Added ${entry.station}`;
  renderList();
});

renderList();
