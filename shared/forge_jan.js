/* The Jan settings panel every app shares.
 *
 * An app that mounts shared/forge_jan.py gets /api/jan/settings; this draws it:
 * one model picker per role the app declared, and how long a model may sit idle
 * before its memory is given back. A slider paired with a number box, as every
 * numeric setting in Forge is.
 *
 *     <div id="jan-settings"></div>
 *     <script src="/shared/forge_jan.js"></script>
 *     <script>ForgeJan.panel(document.getElementById("jan-settings"));</script>
 *
 * Labels for the roles are the app's business: pass { labels: { chatter: "NPC
 * chatter" } }. Nothing here names a model or an app.
 */
const ForgeJan = (() => {
  "use strict";

  const IDLE_MAX = 60;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function load() {
    const res = await fetch("/api/jan/settings", { cache: "no-store" });
    if (!res.ok) throw new Error("the Jan settings answered " + res.status);
    return res.json();
  }

  async function save(changes) {
    const res = await fetch("/api/jan/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
    if (!res.ok) throw new Error("could not save the Jan settings");
    return (await res.json()).settings;
  }

  function modelRow(role, label, chosen, available, onPick) {
    const row = el("label", "set-row", label);
    const pick = el("select");
    const auto = el("option", null, "Whatever Jan has");
    auto.value = "";
    pick.append(auto);
    for (const id of available) {
      const option = el("option", null, id);
      option.value = id;
      pick.append(option);
    }
    // A model that is set but no longer installed still shows, so the setting
    // is never silently changed underneath the person.
    if (chosen && !available.includes(chosen)) {
      const gone = el("option", null, chosen + " (not installed)");
      gone.value = chosen;
      pick.append(gone);
    }
    pick.value = chosen || "";
    pick.addEventListener("change", () => onPick(pick.value));
    row.append(pick);
    return row;
  }

  function idleRow(minutes, onSet) {
    const row = el("div", "set-row", "Give the memory back after (minutes idle, 0 keeps it loaded)");
    const pair = el("div", "pair");
    const range = el("input");
    range.type = "range";
    const number = el("input");
    number.type = "number";
    for (const input of [range, number]) {
      input.min = "0";
      input.max = String(IDLE_MAX);
      input.step = "1";
      input.value = String(Math.round(minutes));
    }
    const set = (raw) => {
      const value = Math.max(0, Math.min(IDLE_MAX, Math.round(Number(raw) || 0)));
      range.value = number.value = String(value);
      onSet(value);
    };
    range.addEventListener("input", () => set(range.value));
    number.addEventListener("change", () => set(number.value));
    pair.append(range, number);
    row.append(pair);
    return row;
  }

  async function panel(host, options = {}) {
    if (!host) return null;
    const labels = options.labels || {};
    host.innerHTML = "";
    let data;
    try {
      data = await load();
    } catch (err) {
      host.append(el("p", "muted small", "Jan settings unavailable: " + err.message));
      return null;
    }
    const { settings, models, roles, running, loaded } = data;
    const say = el("p", "muted small");
    const refresh = () => {
      say.textContent = running
        ? (loaded.length
            ? "Jan is running. Loaded now: " + loaded.join(", ")
            : "Jan is running with no model loaded. The first request loads the one you pick.")
        : "Jan is not running. Models load when you start it and use this app.";
    };
    refresh();

    for (const role of roles.length ? roles : Object.keys(settings.models)) {
      host.append(
        modelRow(role, labels[role] || "Model for " + role, settings.models[role] || "", models, (value) =>
          save({ models: { [role]: value } }).catch(() => {})
        )
      );
    }
    host.append(
      idleRow(settings.idle_minutes, (value) => save({ idle_minutes: value }).catch(() => {}))
    );
    host.append(say);
    return data;
  }

  return { panel, load, save };
})();
window.ForgeJan = ForgeJan;
