/* Crucible's stepping thread: holds the world and steps it (see stepper.js). */

import { host } from "./stepper.js";

const handle = host();
self.onmessage = (e) => {
  const out = handle(e.data);
  if (out) self.postMessage(out.msg, out.transfer);
};
