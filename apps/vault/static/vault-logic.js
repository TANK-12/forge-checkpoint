// Pure helpers for the Vault page, tested with node --test.

export function size(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

// The places this item can go, in registry order.
export function targetsFor(item, targets) {
  return targets.filter((t) => t.kinds.includes(item.kind));
}

// How the page shows an item: "3d", "sky", "image", "audio" or "none".
export function previewMode(item, kinds) {
  const kind = kinds.find((k) => k.id === item.kind);
  if (!kind) return "none";
  if (kind.preview_exts && !kind.preview_exts.includes(item.ext)) return "none";
  return kind.preview || "none";
}

// The address of one of an item's files; each path part is escaped so a
// name with # or ? still reaches the server.
export function fileUrl(item, rel) {
  const part = (rel || item.path.slice(item.dir.length + 1))
    .split("/")
    .map(encodeURIComponent)
    .join("/");
  return `/api/items/${item.id}/f/${part}`;
}
