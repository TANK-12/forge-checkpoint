/* The System section of Settings (moved here from the Claude app on
 * 2026-10-19). Panels come from /api/system/panels (system_settings/panels.json)
 * in registry order; each has a draw function below keyed by its id. A panel
 * without one shows its raw status, so a new backend panel is visible before
 * it has a face. Changes POST to /api/system/<panel>/<action> and redraw from
 * the fresh status that comes back.
 *
 * It lives in the card #system-panel, which app.js lists like every other
 * section (sidebar, tabs, one page, pins, search). Each panel's button is an
 * `.item` with the panel's words in data-search, so the Settings search
 * finds it; picking a found panel leaves the search and opens it. Nothing is
 * read from the laptop until the card is on screen.
 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  // a release leaves the page out (FORGE_CUT_PAGES): nothing to draw
  if (!$("system-panel")) return;
  const H = { "X-Forge": "1" };
  const KEY = "forge.settings.system";
  let panels = [];
  let current = null;
  let busy = 0;
  let onScreen = false;
  let drawn = "";  // the panel and status last drawn, to skip a re-read that brings nothing new
  // What a status looks like for that comparison. An action's answer carries
  // a `done` note that a plain read never has; left in, the first quiet
  // re-read after every action looked new and rebuilt the panel.
  const drawKey = (data) => {
    const { done: _note, ...status } = data && typeof data === "object" ? data : { value: data };
    return current + JSON.stringify(status);
  };
  const shown = () => (window.ForgeIdle ? ForgeIdle.shown() : !document.hidden);

  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (k === "checked" || k === "disabled" || k === "value") node[k] = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  function say(text, bad) {
    const node = $("sys-said");
    node.textContent = text || "";
    node.title = text || "";
    node.classList.toggle("bad", !!bad);
  }

  async function api(path, body) {
    const opts = body === undefined
      ? { headers: H }
      : { method: "POST", headers: { ...H, "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch (_) { /* not JSON */ }
    if (!r.ok) throw new Error((data && data.detail) || `${r.status} ${r.statusText}`);
    return data;
  }

  // One change: POST, then draw the fresh status. Long ones (pairing, a
  // Bluetooth scan, joining Wi-Fi) say what they are doing meanwhile.
  // A slider passes redraw=false: redrawing would replace the slider being
  // dragged.
  async function act(action, body, doing, redraw = true) {
    const panel = current;
    busy++;
    say(doing || "…");
    try {
      const data = await api(`/api/system/${panel}/${action}`, body || {});
      if (panel === current && redraw) draw(data);
      say(doing ? "done" : "");
      return data;
    } catch (err) {
      say(err.message, true);
      // redraw even if nothing changed: a switch flipped here must flip back
      if (panel === current) load(true, true);
      return null;
    } finally {
      busy--;
    }
  }

  // A slider sends while dragging, one change at a time and at most every
  // 150 ms, so the last value is the one that sticks.
  function throttled(fn) {
    let timer = null;
    let pending = null;
    let running = false;
    async function flush() {
      timer = null;
      if (running || pending === null) return;
      const value = pending;
      pending = null;
      running = true;
      try {
        await fn(value);
      } finally {
        running = false;
        if (pending !== null) timer = setTimeout(flush, 150);
      }
    }
    return (value) => {
      pending = value;
      if (!timer && !running) timer = setTimeout(flush, 150);
    };
  }

  function switchBox(checked, onchange, title, disabled) {
    return el("input", { type: "checkbox", class: "s-switch", checked, disabled, title, "aria-label": title, onchange: (e) => onchange(e.target.checked) });
  }

  // A slider paired with a number box: either one sets the other, and both
  // send through the same one-at-a-time sender.
  function slider(value, min, max, label, onvalue, unit = "%") {
    const send = throttled(onvalue);
    const box = el("input", {
      type: "number", class: "s-numin", min, max, step: 1, value, "aria-label": `${label} (number)`, title: label,
      onchange: (e) => {
        let v = Math.round(Number(e.target.value));
        if (!Number.isFinite(v)) v = Number(range.value);
        v = Math.min(max, Math.max(min, v));
        e.target.value = v;
        range.value = v;
        send(v);
      },
    });
    const range = el("input", {
      type: "range", class: "s-range", min, max, value, "aria-label": label, title: label,
      oninput: (e) => { box.value = e.target.value; send(Number(e.target.value)); },
    });
    return [range, el("span", { class: "s-num" }, box, el("span", { class: "s-unit", text: unit.trim() }))];
  }

  function mb(n) {
    return n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${Math.round(n)} MB`;
  }

  function ago(seconds) {
    if (seconds < 90) return "just now";
    if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
    return `${(seconds / 3600).toFixed(1)} h`;
  }

  function unavailable(data) {
    return el("div", { class: "s-card" }, el("p", { class: "muted", text: `Not available here: ${data.why || "the system tool did not answer"}.` }));
  }

  // ------------------------------------------------------------ auto-close

  let acFilter = "";

  function autoclose(data) {
    const kill = data.kill_percent;
    const top = el("div", { class: "ac-top" },
      el("div", { class: "s-card" },
        el("div", { class: "s-sub", text: "RAM guard" }),
        el("div", { class: "s-name", text: data.guard_running ? "Running" : "Not seen lately" }),
        el("div", { class: "s-sub", text: data.guard_running ? "It checks every few seconds." : "The forge-ram-guard service has not written its status in a while." })),
      el("div", { class: "s-card" },
        el("div", { class: "s-sub", text: "RAM now" }),
        el("div", { class: "s-name", text: data.ram_percent == null ? "unknown" : `${Math.round(data.ram_percent)}%` }),
        el("div", { class: "s-sub", text: `Warns at ${data.warn_percent}%. At ${kill}% it closes things in order, whatever the rules below say.` })),
      el("div", { class: "s-card" },
        el("div", { class: "s-sub", text: "Window focus" }),
        el("div", { class: "s-name", text: data.focus === "on" ? "Used" : "Not available yet" }),
        el("div", { class: "s-sub", text: data.focus === "on" ? "A focused window counts as in use." : "Needs the Forge desktop extension's new version: log out and in once. Until then, requests and CPU count as use." })));

    const filter = el("input", {
      type: "search", class: "s-in ac-filter", placeholder: "Filter by name", value: acFilter, "aria-label": "Filter",
      oninput: (e) => { acFilter = e.target.value; drawRows(); },
    });
    const rows = el("div", { class: "ac-rows" });
    const head = el("div", { class: "ac-head" },
      el("span", { text: "What" }), el("span", { text: "On" }), el("span", { text: "Close when RAM is at" }),
      el("span", { text: "Close when unused for" }), el("span", { text: "Now" }), el("span"));

    function ramChoices(t) {
      const low = t.ram_low;
      const high = t.ram_high;
      const emergency = Math.max(kill, t.min_percent || 0);
      if (low > high) return [["", `Emergency only (${emergency}%)`]];
      const values = [];
      for (let v = Math.ceil(low / 5) * 5; v <= high; v += 5) values.push(v);
      if (!values.includes(low)) values.unshift(low);
      if (!values.includes(high)) values.push(high);
      return [["", `Emergency only (${emergency}%)`], ...values.map((v) => [String(v), `${v}%`])];
    }

    function idleChoices(t, rule) {
      const values = [...data.idle_choices];
      if (rule.idle_minutes && !values.includes(rule.idle_minutes)) values.push(rule.idle_minutes);
      values.sort((a, b) => a - b);
      return values.map((v) => [String(v), v === 0 ? "Never" : v < 60 ? `${v} min` : `${v / 60} h`]);
    }

    function select(choices, value, label, onchange, disabled, title) {
      return el("select", { class: "s-sel", "aria-label": label, title: title || label, disabled, onchange: (e) => onchange(e.target.value) },
        choices.map(([v, text]) => el("option", { value: v, selected: v === value ? "selected" : null, text })));
    }

    function row(t) {
      const r = t.rule.enabled ? t.rule : { ...t.rule, ...t.rule.chosen };
      const save = (change, doing) => act("rule", { name: t.name, change }, doing);
      const seen = t.seen;
      const now = !data.guard_running ? "" : !seen ? "not running" : `${mb(seen.mb)} · used ${seen.idle_seconds < 90 ? "just now" : `${ago(seen.idle_seconds)} ago`}`;
      const sub = t.kind === "app" ? "Forge app" : (t.note || t.group_label);
      return el("div", { class: `s-card ac-row${r.enabled ? "" : " off"}`, "data-name": t.name },
        el("div", { class: "ac-what" },
          el("div", { class: "s-name" }, t.icon ? `${t.icon} ` : "", t.label),
          el("div", { class: "s-sub", title: sub, text: sub })),
        switchBox(r.enabled, (on) => save({ enabled: on }), `Use these rules for ${t.label}`),
        select(ramChoices(t), r.ram_percent == null ? "" : String(r.ram_percent), `RAM level for ${t.label}`,
          (v) => save({ ram_percent: v === "" ? null : Number(v) }), !r.enabled),
        t.idle_allowed
          ? select(idleChoices(t, r), String(r.idle_minutes), `Idle time for ${t.label}`, (v) => save({ idle_minutes: Number(v) }), !r.enabled)
          : el("span", { class: "s-sub", title: t.idle_why, text: `Never idle-closed${t.idle_why ? `: ${t.idle_why}` : ""}` }),
        el("span", { class: "ac-seen", text: now }),
        el("button", { type: "button", class: "linkish", disabled: !r.custom, title: "Back to the default rule", text: "reset",
          onclick: () => act("reset", { name: t.name }) }));
    }

    function drawRows() {
      const words = acFilter.toLowerCase().split(/\s+/).filter(Boolean);
      const shown = data.targets.filter((t) => words.every((w) => `${t.label} ${t.name} ${t.group_label}`.toLowerCase().includes(w)));
      const sections = [
        ["Models, test browsers and big jobs", shown.filter((t) => t.kind !== "app" && t.idle_allowed)],
        ["Forge apps", shown.filter((t) => t.kind === "app")],
        ["Closed only when RAM runs out", shown.filter((t) => t.kind !== "app" && !t.idle_allowed)],
      ];
      rows.replaceChildren(...sections.filter(([, list]) => list.length).flatMap(([title, list]) => [el("h3", { text: title }), head.cloneNode(true), ...list.map(row)]));
      if (!shown.length) rows.append(el("p", { class: "muted s-empty", text: "Nothing matches." }));
    }
    drawRows();

    const closed = (data.closed || []).slice().reverse();
    const log = closed.length
      ? el("ul", { class: "ac-closed" }, closed.slice(0, 12).map((c) => el("li", {},
          el("span", { class: "muted", text: new Date(c.time * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" }) }),
          ` ${c.label}: ${c.why}${c.dry_run ? " (dry run, not really closed)" : ""}`)))
      : el("p", { class: "muted", text: "Nothing closed yet." });

    return [
      top,
      el("p", { class: "muted", text: `Unused means no requests, almost no CPU and (once focus works) no focused window for the whole time. Anything using under ${data.idle_min_mb} MB is left alone. Apps that can save are asked to first; an app that says it is busy is left alone. A Forge app that was closed starts again when you open it.` }),
      filter, rows,
      el("h3", { text: "Recently closed" }), log,
      el("p", { class: "s-sub", text: `Your rules are kept in ${data.rules_file}.` }),
    ];
  }

  // ------------------------------------------------------------------ sound

  function sound(data) {
    if (!data.available) return unavailable(data);
    const group = (kind, list, title) => [
      el("h3", { text: title }),
      list.length ? el("div", { class: "s-list" }, list.map((d) => el("div", { class: "s-card" },
        el("div", { class: "s-row" },
          el("input", { type: "radio", name: kind, checked: d.default, "aria-label": `Use ${d.label}`, title: `Use ${d.label}`,
            onchange: () => act("default", { kind, name: d.name }) }),
          el("div", { class: "grow" }, el("div", { class: "s-name", text: d.label }), el("div", { class: "s-sub", text: d.default ? "In use" : d.port })),
          el("button", { type: "button", class: "btn", title: d.mute ? "Unmute" : "Mute", text: d.mute ? "🔇 muted" : "🔊",
            onclick: () => act("mute", { kind, name: d.name, mute: !d.mute }) })),
        el("div", { class: "s-row" }, slider(d.volume, 0, 150, `${d.label} volume`, (v) => act("volume", { kind, name: d.name, percent: v }, undefined, false)))))) :
        el("p", { class: "muted", text: "None found." }),
    ];
    return [...group("output", data.outputs, "Output"), ...group("input", data.inputs, "Input")];
  }

  // -------------------------------------------------------------- bluetooth

  // Blocked at the radio (rfkill): the adapter is gone, so the usual on/off
  // switch has nothing to switch. Say why, and offer to turn it on unless a
  // hardware switch or the BIOS holds it off.
  function radioOff(data) {
    return el("div", { class: "s-card" }, el("div", { class: "s-row" },
      el("div", { class: "grow" },
        el("div", { class: "s-name", text: "Bluetooth is off" }),
        el("div", { class: "s-sub", text: `${data.why}.` })),
      data.blocked === "soft" && el("button", {
        type: "button", class: "btn btn-primary", text: "Turn Bluetooth on",
        title: "Lift the radio's block (rfkill) and power the adapter on",
        onclick: () => act("unblock", {}, "turning Bluetooth on…"),
      })));
  }

  function bluetooth(data) {
    if (!data.available) return data.blocked ? radioOff(data) : unavailable(data);
    const devices = data.devices || [];
    const card = (d) => el("div", { class: "s-card" }, el("div", { class: "s-row" },
      el("div", { class: "grow" },
        el("div", { class: "s-name", text: d.name }),
        el("div", { class: "s-sub", text: d.mac })),
      d.battery != null && el("span", { class: "s-badge", text: `🔋 ${d.battery}%` }),
      d.connected ? el("span", { class: "s-badge good", text: "connected" }) : d.paired && el("span", { class: "s-badge", text: "paired" }),
      d.connected
        ? el("button", { type: "button", class: "btn", text: "Disconnect", onclick: () => act("disconnect", { mac: d.mac }, `disconnecting ${d.name}…`) })
        : d.paired
          ? el("button", { type: "button", class: "btn btn-primary", text: "Connect", onclick: () => act("connect", { mac: d.mac }, `connecting ${d.name}…`) })
          : el("button", { type: "button", class: "btn btn-primary", text: "Pair", title: "Pair, trust and connect. Put the device in pairing mode first.", onclick: () => act("pair", { mac: d.mac }, `pairing with ${d.name}…`) }),
      d.paired && el("button", { type: "button", class: "btn", text: "Forget", title: "Remove the pairing",
        onclick: () => { if (confirm(`Forget ${d.name}? You would need to pair it again.`)) act("remove", { mac: d.mac }, `forgetting ${d.name}…`); } })));
    const known = devices.filter((d) => d.paired || d.connected);
    const near = devices.filter((d) => !d.paired && !d.connected);
    return [
      el("div", { class: "s-card" }, el("div", { class: "s-row" },
        el("div", { class: "grow" }, el("div", { class: "s-name", text: data.powered ? "Bluetooth is on" : "Bluetooth is off" }), el("div", { class: "s-sub", text: `${data.name} · ${data.address}` })),
        el("button", { type: "button", class: "btn", disabled: !data.powered, text: "Scan for devices", title: "Look for devices in pairing mode for 10 seconds",
          onclick: () => act("scan", { seconds: 10 }, "scanning for 10 seconds…") }),
        switchBox(data.powered, (on) => {
          if (!on && devices.some((d) => d.connected) && !confirm("Turn Bluetooth off? Connected devices will drop.")) { load(); return; }
          act("power", { on });
        }, "Bluetooth on or off"))),
      el("h3", { text: "Your devices" }),
      known.length ? el("div", { class: "s-list" }, known.map(card)) : el("p", { class: "muted", text: "None paired." }),
      el("h3", { text: "Other devices seen" }),
      near.length ? el("div", { class: "s-list" }, near.map(card)) : el("p", { class: "muted", text: "None. Put a device in pairing mode and press Scan." }),
    ];
  }

  // ------------------------------------------------------------------- wifi

  function bars(signal) {
    const n = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1;
    return el("span", { class: "bars", title: `Signal ${signal}%` }, [1, 2, 3, 4].map((i) => el("i", { class: i <= n ? "on" : "", style: `height:${3 + i * 3}px` })));
  }

  function wifi(data) {
    if (!data.available && !data.devices) return unavailable(data);
    const join = (n) => {
      if (n.saved || !n.secure) return act("connect", { ssid: n.ssid }, `joining ${n.ssid}…`);
      const box = $("sys-main").querySelector(`[data-ssid="${CSS.escape(n.ssid)}"] .pw`);
      box.classList.remove("hidden");
      box.querySelector("input").focus();
      return null;
    };
    const net = (n) => el("div", { class: "s-card", "data-ssid": n.ssid },
      el("div", { class: "s-row" },
        bars(n.signal),
        el("div", { class: "grow" }, el("div", { class: "s-name" }, n.ssid, n.secure ? " 🔒" : ""), el("div", { class: "s-sub", text: `${n.band}${n.security ? ` · ${n.security}` : " · open"}` })),
        n.active ? el("span", { class: "s-badge good", text: "connected" }) : n.saved && el("span", { class: "s-badge", text: "saved" }),
        !n.active && el("button", { type: "button", class: "btn btn-primary", text: "Connect", onclick: () => join(n) })),
      el("form", { class: "s-row pw hidden", onsubmit: (e) => {
        e.preventDefault();
        const password = e.target.querySelector("input").value;
        act("connect", { ssid: n.ssid, password }, `joining ${n.ssid}…`);
      } },
        el("input", { type: "password", class: "s-in", placeholder: "Password", autocomplete: "off", "aria-label": `Password for ${n.ssid}`, minlength: 8, maxlength: 64, required: true }),
        el("button", { type: "submit", class: "btn btn-primary", text: "Join" })));
    const saved = (s) => el("div", { class: "s-card" }, el("div", { class: "s-row" },
      el("div", { class: "grow" }, el("div", { class: "s-name", text: s.name }), el("div", { class: "s-sub", text: s.active ? "Connected now" : "Saved" })),
      el("button", { type: "button", class: "btn", text: "Forget",
        onclick: () => {
          const warn = s.active ? `Forget ${s.name}? You are connected to it now, so this disconnects you, and you will need its password to join again.` : `Forget ${s.name}? You will need its password to join again.`;
          if (confirm(warn)) act("forget", { uuid: s.uuid }, `forgetting ${s.name}…`);
        } })));
    const dev = (data.devices || [])[0];
    return [
      el("div", { class: "s-card" }, el("div", { class: "s-row" },
        el("div", { class: "grow" }, el("div", { class: "s-name", text: data.radio ? (dev && dev.connection ? `Connected to ${dev.connection}` : "Wi-Fi is on") : "Wi-Fi is off" }),
          el("div", { class: "s-sub", text: dev ? `${dev.device} · ${dev.state}` : "" })),
        el("button", { type: "button", class: "btn", disabled: !data.radio, text: "Rescan", onclick: () => act("rescan", {}, "looking for networks…").then(() => setTimeout(() => load(), 4000)) }),
        switchBox(data.radio, (on) => {
          if (!on && !confirm("Turn Wi-Fi off? This disconnects you.")) { load(); return; }
          act("radio", { on });
        }, "Wi-Fi on or off"))),
      el("h3", { text: "Networks in range" }),
      data.networks.length ? el("div", { class: "s-list" }, data.networks.map(net)) : el("p", { class: "muted", text: "None found. Try Rescan." }),
      el("h3", { text: "Saved networks" }),
      data.saved.length ? el("div", { class: "s-list" }, data.saved.map(saved)) : el("p", { class: "muted", text: "None saved." }),
    ];
  }

  // ---------------------------------------------------------------- display

  function display(data) {
    if (!data.available) return unavailable(data);
    const out = [];
    if (data.brightness) {
      out.push(el("h3", { text: "Brightness" }), el("div", { class: "s-card" }, el("div", { class: "s-row" },
        el("span", { text: "🔅" }), slider(data.brightness.percent, 1, 100, "Screen brightness", (v) => act("brightness", { percent: v }, undefined, false)), el("span", { text: "🔆" }))));
    }
    const n = data.night_light;
    if (n) {
      const [lo, hi] = data.kelvin_range;
      const hour = (key, label) => el("input", { type: "number", class: "s-in s-hour", min: 0, max: 23.5, step: 0.5, value: n[`schedule_${key}`], "aria-label": label, title: `${label} (hour, 0 to 24)`, disabled: n.schedule_automatic,
        onchange: (e) => act("night_schedule", { automatic: false, [key]: Number(e.target.value) }) });
      out.push(el("h3", { text: "Night light" }), el("div", { class: "s-card" },
        el("div", { class: "s-row" },
          el("div", { class: "grow" }, el("div", { class: "s-name", text: "Warmer colours at night" }), el("div", { class: "s-sub", text: "GNOME's night light" })),
          switchBox(n.enabled, (on) => act("night_light", { enabled: on }), "Night light on or off")),
        el("div", { class: "s-row" }, el("span", { class: "s-sub", text: "Warmer" }),
          slider(n.temperature, lo, hi, "Night light colour", (v) => act("night_temperature", { kelvin: v }, undefined, false), " K"), el("span", { class: "s-sub", text: "Cooler" })),
        el("div", { class: "s-row" },
          el("label", { class: "s-check" }, el("input", { type: "checkbox", checked: n.schedule_automatic, onchange: (e) => act("night_schedule", { automatic: e.target.checked }) }), " Sunset to sunrise"),
          el("span", { class: "s-sub", text: "or from" }), hour("from", "Night light from"), el("span", { class: "s-sub", text: "to" }), hour("to", "Night light to"))));
    }
    return out;
  }

  // ---------------------------------------------------------------- battery

  function power(data) {
    if (!data.available) return unavailable(data);
    const b = data.battery;
    const open = () => window.parent.postMessage({ forge: "open", role: "power", app: "power" }, "*");
    return [
      b ? el("div", { class: "s-card" },
        el("div", { class: "s-row" },
          el("span", { class: "s-big", text: b.percent == null ? "?" : `${Math.round(b.percent)}%` }),
          el("div", { class: "grow" },
            el("div", { class: "s-name", text: `${b.state.replace(/-/g, " ")}${data.on_power ? " · on the charger" : data.on_power === false ? " · on battery" : ""}` }),
            el("div", { class: "s-sub", text: [b.time_to_empty && data.on_power === false && `${b.time_to_empty} left`, b.time_to_full && `full in ${b.time_to_full}`, b.watts && `drawing ${b.watts}`].filter(Boolean).join(" · ") }))),
        b.health != null && el("div", { class: "s-row s-sub", text: `Battery health: holds ${Math.round(b.health)}% of its design charge.` }))
        : el("div", { class: "s-card" }, el("p", { class: "muted", text: "No battery found." })),
      el("h3", { text: "Power profile and CPU caps" }),
      el("div", { class: "s-card" }, el("div", { class: "s-row" },
        el("div", { class: "grow" }, el("div", { class: "s-name", text: `Profile: ${data.profile || "unknown"}` }),
          el("div", { class: "s-sub", text: "The Power app sets these, with its CPU caps, so they stay in one place." })),
        window.parent !== window && el("button", { type: "button", class: "btn btn-primary", text: "Open Power", onclick: open }))),
    ];
  }

  // ---------------------------------------------------------- notifications

  function notifications(data) {
    if (!data.available) return unavailable(data);
    return [
      el("div", { class: "s-card" }, el("div", { class: "s-row" },
        el("div", { class: "grow" }, el("div", { class: "s-name", text: "Do not disturb" }), el("div", { class: "s-sub", text: data.dnd ? "On: notifications go quietly to the list, no pop-ups." : "Off: notifications pop up." })),
        switchBox(data.dnd, (on) => act("dnd", { on }), "Do not disturb"))),
      data.lock_screen != null && el("div", { class: "s-card" }, el("div", { class: "s-row" },
        el("div", { class: "grow" }, el("div", { class: "s-name", text: "On the lock screen" }), el("div", { class: "s-sub", text: "Show notifications while the screen is locked." })),
        switchBox(data.lock_screen, (on) => act("lock_screen", { on }), "Notifications on the lock screen"))),
    ];
  }

  // ------------------------------------------------------------------ clock

  let tick = null;
  function clock(data) {
    const big = el("div", { class: "s-big" });
    const date = el("div", { class: "s-name" });
    const skew = data.now * 1000 - Date.now();
    const show = () => {
      const t = new Date(Date.now() + skew);
      big.textContent = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      date.textContent = t.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    };
    show();
    clearInterval(tick);
    tick = setInterval(() => (big.isConnected ? shown() && show() : clearInterval(tick)), 1000);
    const yes = (v) => (v == null ? "unknown" : v ? "yes" : "no");
    return [
      el("div", { class: "s-card" }, big, date),
      el("div", { class: "s-card" },
        el("div", { class: "s-row" }, el("span", { class: "grow", text: "Time zone" }), el("span", { text: `${data.timezone} (UTC${data.utc_offset.slice(0, 3)}:${data.utc_offset.slice(3)})` })),
        el("div", { class: "s-row" }, el("span", { class: "grow", text: "Set from the network" }), el("span", { text: yes(data.ntp) })),
        el("div", { class: "s-row" }, el("span", { class: "grow", text: "In sync now" }), el("span", { text: yes(data.synced) }))),
      el("p", { class: "muted", text: "Read-only: changing the clock or time zone needs an administrator password, so use GNOME Settings for that." }),
    ];
  }

  const DRAW = { autoclose, sound, bluetooth, wifi, display, power, notifications, clock };

  // ------------------------------------------------------------------ frame

  function ramChip(data) {
    if (current !== "autoclose" || data.ram_percent == null) return;
    const chip = $("sys-ram");
    const pct = Math.round(data.ram_percent);
    chip.textContent = `RAM ${pct}%`;
    chip.className = `s-chip${pct >= data.kill_percent ? " bad" : pct >= data.warn_percent ? " warn" : ""}`;
  }

  function draw(data) {
    const meta = panels.find((p) => p.id === current) || {};
    const fn = DRAW[current];
    const body = fn ? fn(data) : el("pre", { class: "s-card", text: JSON.stringify(data, null, 2) });
    const main = $("sys-main");
    drawn = drawKey(data);
    const filter = main.querySelector(".ac-filter");
    const keep = filter && document.activeElement === filter ? acFilter : null;
    main.replaceChildren(el("div", { class: "s-panel", "data-panel": current },
      el("h4", {}, `${meta.icon || ""} ${meta.label || current}`),
      el("p", { class: "muted about", text: meta.about || "" }),
      body,
      // A panel naming a reset group (panels.json "reset") gets its reset at
      // the foot: back to the defaults, or forget saved networks or devices.
      meta.reset && typeof Resets !== "undefined"
        ? el("div", { class: "card-foot" }, el("button", {
          type: "button", class: "btn reset-sys", "data-reset-group": meta.reset,
          onclick: () => Resets.run({ group: meta.reset }),
        }, `Reset ${meta.label || current}…`))
        : null));
    if (keep !== null) {
      const box = main.querySelector(".ac-filter");
      if (box) { box.focus(); box.setSelectionRange(keep.length, keep.length); }
    }
    ramChip(data);
  }

  // A quiet re-read (the 20 s check, the card coming on screen) that brings
  // nothing new leaves the panel as it is, and one never closes a Wi-Fi
  // password being typed: rebuilding the rows each time lost their scroll,
  // focus and anything half-typed. `force` redraws anyway.
  async function load(quiet, force) {
    const panel = current;
    if (!panel) return;
    if (!quiet) say("");
    try {
      const data = await api(`/api/system/${panel}`);
      if (panel !== current) return;
      if (quiet && !force) {
        const typing = [...$("sys-main").querySelectorAll(".pw:not(.hidden) input")].some((box) => box.value);
        if (typing || drawKey(data) === drawn) { ramChip(data); return; }
      }
      draw(data);
    } catch (err) {
      say(err.message, true);
    }
  }

  function open(id) {
    if (!panels.some((p) => p.id === id)) id = panels[0].id;
    current = id;
    try { localStorage.setItem(KEY, id); } catch (_) { /* private window */ }
    for (const b of $("sys-nav").querySelectorAll("button[data-id]")) {
      const on = b.dataset.id === id;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    }
    $("sys-main").replaceChildren(el("p", { class: "muted", text: "Reading…" }));
    drawn = "";
    if (onScreen) load();
  }

  // A found panel in a search: leave the search, show the System section
  // (app.js's showSection) and open the panel there.
  function pick(id) {
    const box = $("search");
    if (document.body.classList.contains("searching") && box) {
      box.value = "";
      if (typeof window.showSection === "function") window.showSection("system", true);
    }
    open(id);
    if (!onScreen) { onScreen = true; load(); }
  }

  async function start() {
    try {
      panels = await api("/api/system/panels");
    } catch (err) {
      $("sys-main").replaceChildren(el("p", { class: "muted", text: `Could not list the panels: ${err.message}` }));
      return;
    }
    $("sys-nav").replaceChildren(...panels.map((p) => el("button", {
      type: "button", class: "item sys-tab", role: "tab", "data-id": p.id, title: p.about,
      "data-search": [p.label, p.about, p.keywords, "system"].filter(Boolean).join(" "),
      onclick: () => pick(p.id),
    }, el("span", { class: "ic", "aria-hidden": "true", text: p.icon }), el("span", { text: p.label }))));
    let first = "";
    try { first = localStorage.getItem(KEY) || ""; } catch (_) { /* private window */ }
    open(first);
    $("sys-refresh").addEventListener("click", () => load());
    // a reset (resets.js) may have changed the laptop: read the panel again
    window.addEventListener("forge-reset", () => load(true, true));
    // Read the laptop only while the card is on screen: opening it (or
    // scrolling to it on the one-page layout) reads the open panel afresh.
    new IntersectionObserver((seen) => {
      const now = seen.some((s) => s.isIntersecting);
      if (now && !onScreen) load(true);
      onScreen = now;
    }).observe($("system-panel"));
    document.addEventListener("keydown", (e) => {
      if (!onScreen || e.ctrlKey || e.metaKey || e.altKey || document.body.classList.contains("searching")) return;
      if (e.target.closest && e.target.closest("input, select, textarea")) return;
      if (e.key === "r") load();
    });
    // keep the open panel current while nothing is being changed
    setInterval(() => {
      const focus = document.activeElement;
      if (!busy && onScreen && shown() && current !== "clock" && !(focus && focus.closest("input, select"))) load(true);
    }, 20000);
  }

  start();
})();
