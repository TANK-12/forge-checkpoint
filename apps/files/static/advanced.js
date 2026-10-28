/* Optional power tools. Simple remains the first-run view. */
"use strict";
(() => {
  let active = false;
  let preview = null;
  let ticket = 0;
  try { active = localStorage.getItem("files.advanced") === "true"; } catch { /* private mode */ }
  const button = $("advanced-toggle");
  const showMode = () => {
    button.setAttribute("aria-pressed", String(active));
    button.classList.toggle("on", active);
    $("advanced-tools").classList.toggle("hidden", !active);
    if (!active) { $("advanced-result").classList.add("hidden"); ticket++; }
  };
  const output = (text) => {
    $("advanced-result").textContent = text;
    $("advanced-result").classList.remove("hidden");
  };
  window.FilesAdvanced = {
    filter(items) {
      if (!active) return items;
      const kind = $("filter-kind").value;
      const extension = $("filter-ext").value.trim().toLowerCase();
      const minimum = Number($("filter-size").value) || 0;
      return items.filter(item => (!kind || (kind === "folder" ? item.dir : kind === "file" ? !item.dir : item.kind === kind)) &&
        (!extension || item.name.toLowerCase().endsWith(extension.startsWith(".") ? extension : "." + extension)) &&
        (!minimum || (!item.dir && item.size >= minimum)));
    }
  };
  button.onclick = () => {
    active = !active;
    try { localStorage.setItem("files.advanced", String(active)); } catch { /* private mode */ }
    showMode(); render();
  };
  for (const id of ["filter-kind", "filter-ext", "filter-size"]) $(id).oninput = render;
  const inspect = async (kind) => {
    const paths = [...S.sel];
    if ((kind === "hash" && paths.length !== 1) || paths.length > 1) { toast("Select one item first", "err"); return; }
    const path = paths[0] || S.path;
    const seq = ++ticket;
    output(`Reading ${path}…`);
    try {
      const data = await api(`/api/advanced/${kind}?${q({path})}`);
      if (seq !== ticket || !active) return;
      if (kind === "inspect") output(`${data.path}\nOwner: ${data.owner} (${data.uid})    Group: ${data.group} (${data.gid})\nPermissions: ${data.permissions} (${data.mode})\nSize: ${data.bytes.toLocaleString()} bytes    Allocated: ${data.allocated.toLocaleString()} bytes\nModified: ${new Date(data.modified * 1000).toLocaleString()}\nInode: ${data.inode}    Device: ${data.device}    Hard links: ${data.links}${data.link ? "\nLink target: " + data.link : ""}`);
      else if (kind === "hash") output(`${path}\nSHA-256: ${data.sha256}\n${data.bytes.toLocaleString()} bytes checked`);
      else output(`${path}\n${data.partial ? "Partial result (scan limit reached)" : "Scan finished"}: ${data.files} files, ${data.bytes.toLocaleString()} logical bytes, ${data.allocated.toLocaleString()} allocated bytes\n${data.skipped} links, mount boundaries or unreadable entries skipped. Hard links counted once.`);
    } catch (error) { if (seq === ticket && active) output(error.message); }
  };
  $("inspect-item").onclick = () => inspect("inspect");
  $("hash-item").onclick = () => inspect("hash");
  $("usage-folder").onclick = () => inspect("usage");
  $("terminal-here").onclick = () => openIn("terminal", `cwd=${encodeURIComponent(S.path)}`);
  $("edit-path").onclick = () => { $("crumbs").dispatchEvent(new MouseEvent("dblclick", {bubbles:true})); };
  $("batch-rename").onclick = () => {
    if (!S.sel.size) { toast("Select the items to rename", "err"); return; }
    preview = null; $("batch-apply").disabled = true; $("batch-plan").textContent = "";
    $("batch-dialog").showModal();
  };
  const invalidate = () => { preview = null; $("batch-apply").disabled = true; };
  for (const id of ["batch-find", "batch-replace", "batch-prefix"]) $(id).oninput = invalidate;
  $("batch-close").onclick = () => $("batch-dialog").close();
  $("batch-preview").onclick = async () => {
    invalidate();
    try {
      const data = await api("/api/advanced/rename/preview", {body:{paths:[...S.sel], find:$("batch-find").value, replace:$("batch-replace").value, prefix:$("batch-prefix").value}});
      preview = data.plan;
      $("batch-plan").textContent = preview.map(item => `${baseName(item.path)} → ${item.name}`).join("\n");
      $("batch-apply").disabled = false;
    } catch (error) { $("batch-plan").textContent = error.message; }
  };
  $("batch-form").onsubmit = async (event) => {
    event.preventDefault();
    if (!preview) return;
    const plan = preview; invalidate();
    try {
      const data = await api("/api/advanced/rename/apply", {body:{plan}});
      $("batch-dialog").close();
      output(`${data.renamed.length} items renamed.${data.error ? " Stopped: " + data.error : ""}`);
      await refresh();
    } catch (error) { $("batch-plan").textContent = error.message; }
  };
  showMode();
})();
