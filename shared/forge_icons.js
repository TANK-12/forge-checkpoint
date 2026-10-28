// Forge app icons: one glyph per app id, all drawn in one shared style.
//
// Every glyph sits on a 24x24 grid and is drawn with a 1.8 round stroke in
// currentColor, so it takes the colour of whatever holds it (the hub tints
// each app's icon tile with the app's accent). Two extra marks give depth:
//   class="d"  a soft fill (currentColor at 30%), for a body or a backdrop
//   class="s"  a solid fill (currentColor), for small details and dots
// Mission alone adds the Claude orange to its spark, on purpose (and the Pixel
// games heart a white glint).
//
// Adding an app: one entry below, keyed by its folder name in apps/ (a folder
// of apps: its file name in groups/). Without an entry it keeps the emoji from
// its "icon" field.
//
// Two styles, one flag (Settings > Glass and layout > Icons, the setting
// icon_style): "new" draws the glyphs below, "classic" shows the emoji in
// CLASSIC, the icons Forge had before the glyphs (2026-10-07), with the
// repeats fixed so no two apps share one. An app needs an entry in both.
//
//   ForgeIcons.svg(id)               -> "<svg ...>" markup, or "" if unknown
//   ForgeIcons.classic(id)           -> the app's classic emoji, or ""
//   ForgeIcons.paint(el, id, text)   -> fills el with the app's icon in the
//                                       current style, else text
//   ForgeIcons.forget(el)           -> el no longer follows the style
//   ForgeIcons.style(), ForgeIcons.setStyle("new" | "classic")
//                                    -> switches and repaints every painted
//                                       icon on the page in place
//   ForgeIcons.has(id), ForgeIcons.ids(), ForgeIcons.styles
(function () {
  const GLYPHS = {
    // Claude-style spark, with Claude sessions riding an orbit around it
    mission:
      '<path transform="translate(12 12) scale(.94) translate(-12 -12)" d="M15.3 7.4C19.7 4.9 22.8 4.2 23.2 5.3c.5 1.6-3.6 5.3-9.6 8.5s-11.9 4.8-12.4 3.2c-.3-.9 1.1-2.5 3.6-4.3" stroke-width="1.4" stroke-opacity=".75"/>' +
      '<path class="c" stroke="#e8875f" stroke-width="1" transform="translate(12 12) scale(1.32) translate(-12 -12)" d="M11.75 10.72 L12.45 5.62 L12.42 10.77 L14.74 7.94 L12.98 11.15 L17.21 9.46 L13.28 11.75 L16.59 12.32 L13.23 12.42 L17.47 15.69 L12.85 12.98 L14.19 16.49 L12.25 13.28 L11.60 17.69 L11.58 13.23 L9.54 15.65 L11.02 12.85 L6.43 14.72 L10.72 12.25 L6.91 11.64 L10.77 11.58 L7.11 8.70 L11.15 11.02 L9.94 7.78Z"/>' +
      '<circle class="s" cx="21" cy="6.9" r="1.5"/><circle class="s" cx="3.2" cy="15.9" r="1.5"/><circle class="s" cx="9.2" cy="16.1" r="1"/>',
    // a chat bubble with the Claude spark inside
    claude:
      '<path class="d" d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z"/>' +
      '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5z"/>' +
      '<path fill="currentColor" stroke-width="1" transform="translate(12 9.5) scale(.62) translate(-12 -12)" d="M11.75 10.72 L12.45 5.62 L12.42 10.77 L14.74 7.94 L12.98 11.15 L17.21 9.46 L13.28 11.75 L16.59 12.32 L13.23 12.42 L17.47 15.69 L12.85 12.98 L14.19 16.49 L12.25 13.28 L11.60 17.69 L11.58 13.23 L9.54 15.65 L11.02 12.85 L6.43 14.72 L10.72 12.25 L6.91 11.64 L10.77 11.58 L7.11 8.70 L11.15 11.02 L9.94 7.78Z"/>',
    // a cat face
    acchan:
      '<path class="d" d="M4.5 11V4l4.4 3.3a9 9 0 0 1 6.2 0L19.5 4v7c0 4.4-3.4 8-7.5 8s-7.5-3.6-7.5-8z"/>' +
      '<path d="M4.5 11V4l4.4 3.3a9 9 0 0 1 6.2 0L19.5 4v7c0 4.4-3.4 8-7.5 8s-7.5-3.6-7.5-8z"/>' +
      '<circle class="s" cx="9.2" cy="12" r="1.2"/><circle class="s" cx="14.8" cy="12" r="1.2"/>' +
      '<path d="M11 14.8l1 .8 1-.8M1.8 13.5l3 .4M1.8 16.6l3-.9M22.2 13.5l-3 .4M22.2 16.6l-3-.9"/>',
    // a sun gone down behind the horizon, its glow and one spark left over
    afterglow:
      '<path class="d" d="M5.5 16.5a6.5 6.5 0 0 1 13 0z"/>' +
      '<path d="M5.5 16.5a6.5 6.5 0 0 1 13 0M2 16.5h20M6.5 20h11"/>' +
      '<path class="s" d="M19 2.5l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8z"/>' +
      '<circle class="s" cx="15.5" cy="6" r=".9"/>',
    // a magic wand making a picture
    "ai-studio":
      '<rect class="d" x="3" y="8" width="13" height="13" rx="2.5"/>' +
      '<rect x="3" y="8" width="13" height="13" rx="2.5"/>' +
      '<path d="M3.5 18.5l4-4 3 3 2-2 3.5 3.5"/>' +
      '<path class="s" d="M18.5 2l1.1 2.9 2.9 1.1-2.9 1.1-1.1 2.9-1.1-2.9-2.9-1.1 2.9-1.1z"/>' +
      '<circle class="s" cx="12" cy="4" r="1"/>',
    // a game pad
    arcade:
      '<path class="d" d="M7 6.5h10a5 5 0 0 1 4.9 4.2l.9 5.6a2.6 2.6 0 0 1-4.6 2.1L16.4 16H7.6l-1.8 2.4a2.6 2.6 0 0 1-4.6-2.1l.9-5.6A5 5 0 0 1 7 6.5z"/>' +
      '<path d="M7 6.5h10a5 5 0 0 1 4.9 4.2l.9 5.6a2.6 2.6 0 0 1-4.6 2.1L16.4 16H7.6l-1.8 2.4a2.6 2.6 0 0 1-4.6-2.1l.9-5.6A5 5 0 0 1 7 6.5z"/>' +
      '<path d="M7.5 9.5v4M5.5 11.5h4"/><circle class="s" cx="15.5" cy="10.2" r="1.2"/><circle class="s" cx="17.8" cy="12.6" r="1.2"/>',
    // a folded map with a pin on it
    atlas:
      '<path class="d" d="M9 4.5l6 2v13l-6-2z"/>' +
      '<path d="M3 6.5l6-2 6 2 6-2v13l-6 2-6-2-6 2z"/><path d="M9 4.5v13M15 6.5v13"/>' +
      '<path d="M18 13.2c-1.3-1.5-2.2-2.7-2.2-3.8a2.2 2.2 0 0 1 4.4 0c0 1.1-.9 2.3-2.2 3.8z"/><circle class="s" cx="18" cy="9.4" r=".8"/>',
    // a pinned note
    board:
      '<path class="d" d="M5 4h14v11l-5 5H5z"/>' +
      '<path d="M5 4h14v11l-5 5H5zM19 15h-5v5"/>' +
      '<path d="M8.5 9h7M8.5 12.5h4.5"/><circle class="s" cx="12" cy="4" r="2"/>',
    // a globe
    browser:
      '<circle class="d" cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="9"/>' +
      '<path d="M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z"/>',
    // a calendar page with today marked
    calendar:
      '<rect class="d" x="3.5" y="5" width="17" height="15.5" rx="2.5"/>' +
      '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/>' +
      '<path d="M3.5 10h17M8 3v4M16 3v4"/><rect class="s" x="13.4" y="13.4" width="3.6" height="3.6" rx="1"/>',
    // a lab flask with bubbles
    "codec-lab":
      '<path class="d" d="M6.4 15.5h11.2l2.3 3.8A1.8 1.8 0 0 1 18.4 22H5.6a1.8 1.8 0 0 1-1.5-2.7z"/>' +
      '<path d="M9.5 2.5h5M10.3 2.5v6.3L4.1 19.3A1.8 1.8 0 0 0 5.6 22h12.8a1.8 1.8 0 0 0 1.5-2.7l-6.2-10.5V2.5"/>' +
      '<circle class="s" cx="10" cy="18.5" r="1.1"/><circle class="s" cx="14" cy="17.6" r=".8"/><circle cx="13.6" cy="12.2" r=".9" stroke-width="1.3"/>',
    // a film frame with a play button
    "codec-player":
      '<rect class="d" x="2.5" y="4.5" width="19" height="15" rx="3"/>' +
      '<rect x="2.5" y="4.5" width="19" height="15" rx="3"/>' +
      '<path class="s" d="M10 8.6v6.8l5.6-3.4z"/><path d="M6 4.5v15M18 4.5v15" stroke-width="1.2" stroke-dasharray="1.6 1.9"/>',
    // code brackets
    code:
      '<rect class="d" x="2.5" y="3.5" width="19" height="17" rx="3"/>' +
      '<path d="M8.5 8l-4 4 4 4M15.5 8l4 4-4 4M13.3 6.5l-2.6 11"/>',
    // a comic burst with a download arrow (saves series as CBZ)
    comix:
      '<path class="d" d="M12 2l2.2 3.6 4-1.4-.5 4.2 4 1.4-3 3 2.5 3.4-4.2.6-.4 4.2-3.9-1.8L9.6 22.1l-1.3-4-4.2.3 1.3-4-3.6-2.3 3.4-2.5-1.4-4 4.2.4z"/>' +
      '<path d="M12 2l2.2 3.6 4-1.4-.5 4.2 4 1.4-3 3 2.5 3.4-4.2.6-.4 4.2-3.9-1.8L9.6 22.1l-1.3-4-4.2.3 1.3-4-3.6-2.3 3.4-2.5-1.4-4 4.2.4z"/>' +
      '<path d="M12 8.2v6.4M9.4 12l2.6 2.6 2.6-2.6"/>',
    // two pages, an arrow from each round to the other
    convert:
      '<rect class="d" x="13" y="11" width="8" height="10" rx="2"/>' +
      '<rect x="3" y="3" width="8" height="10" rx="2"/><rect x="13" y="11" width="8" height="10" rx="2"/>' +
      '<path d="M14 4.5h2.5A2.5 2.5 0 0 1 19 7v1.5M17 6.8l2 2 2-2M10 19.5H7.5A2.5 2.5 0 0 1 5 17v-1.5M3 17.2l2-2 2 2"/>',
    // a ringed planet and a star
    cosmos:
      '<circle class="d" cx="12" cy="12" r="5.6"/><circle cx="12" cy="12" r="5.6"/>' +
      '<path d="M7.6 9.6C3.6 8 1.2 8.3 1.5 9.6c.4 1.9 5.2 4.4 10.8 5.9s10.6 1.3 10.2-.6c-.3-1.3-2.5-2.5-6.2-3.6"/>' +
      '<path class="s" d="M19.5 2.5l.6 1.6 1.6.6-1.6.6-.6 1.6-.6-1.6-1.6-.6 1.6-.6z"/>',
    // a sofa
    crewroom:
      '<path class="d" d="M5 13V8a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v5z"/>' +
      '<path d="M5 11.5V8a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v3.5"/>' +
      '<path d="M3.5 11a1.8 1.8 0 0 1 1.8 1.8V14h13.4v-1.2A1.8 1.8 0 1 1 22 13v4.5a1.5 1.5 0 0 1-1.5 1.5h-17A1.5 1.5 0 0 1 2 17.5V13a1.8 1.8 0 0 1 1.5-2zM5 19v2M19 19v2"/>',
    // a profile sheet: a sourced file on a person or country
    dossier:
      '<path class="d" d="M6 2.5h8.5l4.5 4.5v12.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2z"/>' +
      '<path d="M6 2.5h8.5l4.5 4.5v12.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2zM14.5 2.5V7H19"/>' +
      '<circle class="s" cx="9.5" cy="9.5" r="2"/><path d="M6.8 14.8a3 3 0 0 1 5.4 0M8 18h8M14 11h2"/>',
    // twin peaks and a carving line
    driftpeaks:
      '<path class="d" d="M1.5 19.5l6.5-10 3.5 5 3.5-7.5 7.5 12.5z"/>' +
      '<path d="M1.5 19.5l6.5-10 3.5 5 3.5-7.5 7.5 12.5z"/>' +
      '<path d="M13 9.6l2 1.2 1.8-1.5M6.4 12l1.6-.8 1.4.9"/><path d="M3 22c4-1.2 7.2-3.4 10-1.6 2.4 1.5 5.4 1.2 8-.4" stroke-width="1.4"/>',
    // a walker mech (the Juggernaut)
    eightysix:
      '<path class="d" d="M7 7.5h10l2 4-2 3.5H7l-2-3.5z"/>' +
      '<path d="M7 7.5h10l2 4-2 3.5H7l-2-3.5zM9 4.5h6l1 3H8z"/>' +
      '<path d="M7.6 15l-3.1 3.2 1 3.3M16.4 15l3.1 3.2-1 3.3M9.8 15l-1 4.5M14.2 15l1 4.5"/>' +
      '<circle class="s" cx="12" cy="11.2" r="1.5"/>',
    // a flame with an ember
    emberfield:
      '<path class="d" d="M12 2.5c.8 3.5 5.5 5.6 5.5 11a5.5 5.5 0 0 1-11 0c0-2.6 1.3-4.1 2.4-5.4.3 1.6 1 2.6 2 3-.5-3.5.5-6.4 1.1-8.6z"/>' +
      '<path d="M12 2.5c.8 3.5 5.5 5.6 5.5 11a5.5 5.5 0 0 1-11 0c0-2.6 1.3-4.1 2.4-5.4.3 1.6 1 2.6 2 3-.5-3.5.5-6.4 1.1-8.6z"/>' +
      '<path class="s" d="M12 13c1.1 1.4 2.3 2.4 2.3 3.8a2.3 2.3 0 0 1-4.6 0c0-1.4 1.2-2.4 2.3-3.8z"/>',
    // a flexed exoskeleton arm on a back strut: shoulder drive, struts, elbow drive, cuffs, fist
    exolab:
      '<path d="M5.5 11.2v10.3" stroke-opacity=".55"/>' +
      '<circle class="d" cx="5.5" cy="8" r="3.2"/><circle cx="5.5" cy="8" r="3.2"/><circle class="s" cx="5.5" cy="8" r="1.1"/>' +
      '<circle cx="15.2" cy="17" r="2.4"/>' +
      '<rect class="d" x="16.8" y="2" width="5.4" height="4.6" rx="1.6"/><rect x="16.8" y="2" width="5.4" height="4.6" rx="1.6"/>' +
      '<path d="M7.85 10.2l5.6 5.17M16.1 14.8l3.4-8.2M9.5 14l2.2-2.35M16.3 10l3 1.2"/>',
    // a folder
    files:
      '<path class="d" d="M2.5 8h19v10a2.5 2.5 0 0 1-2.5 2.5H5A2.5 2.5 0 0 1 2.5 18z"/>' +
      '<path d="M2.5 18V6A2.5 2.5 0 0 1 5 3.5h4l2.2 2.5H19A2.5 2.5 0 0 1 21.5 8.5V18a2.5 2.5 0 0 1-2.5 2.5H5A2.5 2.5 0 0 1 2.5 18zM2.5 9.5h19"/>',
    // a telescope on a tripod
    foresight:
      '<path class="d" d="M3.4 11.5l12.8-6.9 2.4 4.4-12.8 6.9z"/>' +
      '<path d="M3.4 11.5l12.8-6.9 2.4 4.4-12.8 6.9zM16.2 4.6l2.6-1.4 2.4 4.4-2.6 1.4M2.3 12.1l1.1-.6 2.4 4.4-1.1.6"/>' +
      '<path d="M11.5 13.2l-3.5 8.3M11.5 13.2l3.5 8.3M11.5 13.2v8.3"/>',
    // an open book (a reader)
    inkforge:
      '<path class="d" d="M2.5 5.5c3.6-.8 6.8-.3 9.5 1.6 2.7-1.9 5.9-2.4 9.5-1.6v13c-3.6-.8-6.8-.3-9.5 1.6-2.7-1.9-5.9-2.4-9.5-1.6z"/>' +
      '<path d="M2.5 5.5c3.6-.8 6.8-.3 9.5 1.6 2.7-1.9 5.9-2.4 9.5-1.6v13c-3.6-.8-6.8-.3-9.5 1.6-2.7-1.9-5.9-2.4-9.5-1.6zM12 7.1v13"/>' +
      '<path d="M5.5 9.5c1.5-.2 2.9 0 4 .5M5.5 12.5c1.5-.2 2.9 0 4 .5M14.5 10c1.1-.5 2.5-.7 4-.5" stroke-width="1.3"/>',
    // a space station: hub, mast and solar wings
    janhollow:
      '<rect class="d" x="1.5" y="8" width="5.5" height="8" rx="1"/><rect class="d" x="17" y="8" width="5.5" height="8" rx="1"/>' +
      '<rect x="1.5" y="8" width="5.5" height="8" rx="1"/><rect x="17" y="8" width="5.5" height="8" rx="1"/>' +
      '<path d="M4.25 8v8M19.75 8v8M7 12h2.5M14.5 12H17M12 4v4.5M12 15.5V20"/>' +
      '<circle cx="12" cy="12" r="3.2"/><circle class="s" cx="12" cy="3.5" r="1.3"/><circle class="s" cx="12" cy="12" r="1.2"/>',
    // tuning sliders, set at their best
    "jan-tune":
      '<path d="M6 3v18M12 3v18M18 3v18" stroke-opacity=".45"/>' +
      '<rect class="s" x="3.4" y="12.6" width="5.2" height="3.6" rx="1.4"/>' +
      '<rect class="s" x="9.4" y="5.6" width="5.2" height="3.6" rx="1.4"/>' +
      '<rect class="s" x="15.4" y="9.6" width="5.2" height="3.6" rx="1.4"/>',
    // a keyboard
    keymap:
      '<rect class="d" x="1.8" y="5.5" width="20.4" height="13" rx="2.5"/>' +
      '<rect x="1.8" y="5.5" width="20.4" height="13" rx="2.5"/>' +
      '<path d="M8 15h8"/><g class="s"><rect x="5" y="8.4" width="2.2" height="2.2" rx=".6"/><rect x="9" y="8.4" width="2.2" height="2.2" rx=".6"/><rect x="13" y="8.4" width="2.2" height="2.2" rx=".6"/><rect x="17" y="8.4" width="2.2" height="2.2" rx=".6"/><rect x="4.6" y="13.9" width="1.8" height="2.2" rx=".6"/><rect x="17.6" y="13.9" width="1.8" height="2.2" rx=".6"/></g>',
    // a key
    logins:
      '<circle class="d" cx="8" cy="12" r="5"/><circle cx="8" cy="12" r="5"/>' +
      '<path d="M13 12h9M18.5 12v3.5M21.5 12v2.5"/><circle class="s" cx="6.8" cy="12" r="1.4"/>',
    // headphones
    media:
      '<path d="M3.5 15v-3a8.5 8.5 0 0 1 17 0v3"/>' +
      '<rect class="d" x="2.5" y="13.5" width="5" height="7.5" rx="2"/><rect class="d" x="16.5" y="13.5" width="5" height="7.5" rx="2"/>' +
      '<rect x="2.5" y="13.5" width="5" height="7.5" rx="2"/><rect x="16.5" y="13.5" width="5" height="7.5" rx="2"/>',
    // a screen with subtitle bars
    mediaforge:
      '<rect class="d" x="2" y="4" width="20" height="14" rx="2.5"/>' +
      '<rect x="2" y="4" width="20" height="14" rx="2.5"/>' +
      '<path d="M8 21h8M6 11.5h5M13.5 11.5H18M6 14.5h9M17.5 14.5h.5"/>',
    // a coin with a mint leaf growing from it
    mint:
      '<circle class="d" cx="10" cy="14" r="7"/><circle cx="10" cy="14" r="7"/>' +
      '<circle cx="10" cy="14" r="4.6" stroke-opacity=".5"/>' +
      '<path class="d" d="M15 9c0-3.6 2.6-6 6.5-6 0 3.7-2.7 6-6.5 6z"/>' +
      '<path d="M15 9c0-3.6 2.6-6 6.5-6 0 3.7-2.7 6-6.5 6zM15 9l3.6-3.6"/>',
    // a price line climbing out of its chart, arrow up
    trader:
      '<path class="d" d="M3.5 19.5l5-6 4 3.5 7.5-9v11.5z"/>' +
      '<path d="M3 3v17.5h18M3.5 19.5l5-6 4 3.5 7.5-9M15.5 8h4.5v4.5"/>',
    // a fountain pen nib (writing)
    novelforge:
      '<path class="d" d="M12 2l5.5 8.5L12 22l-5.5-11.5z"/>' +
      '<path d="M12 2l5.5 8.5L12 22l-5.5-11.5zM12 22v-8.6"/><circle class="s" cx="12" cy="11.6" r="1.7"/>',
    // comic panels, one of them playing
    panelforge:
      '<rect class="d" x="13" y="3" width="8.5" height="18" rx="1.8"/>' +
      '<rect x="2.5" y="3" width="8.5" height="8" rx="1.8"/><rect x="2.5" y="13" width="8.5" height="8" rx="1.8"/>' +
      '<rect x="13" y="3" width="8.5" height="18" rx="1.8"/><path class="s" d="M15.6 9.2v5.6l4.4-2.8z"/>',
    // a pixel invader
    pixelforge:
      '<path class="s" d="M5 4h2v2H5zM17 4h2v2h-2zM7 6h10v2H7zM5 8h14v2H5zM3 10h4v2H3zM9 10h6v2H9zM17 10h4v2h-4zM3 12h18v2H3zM3 14h2v4H3zM7 14h10v2H7zM19 14h2v4h-2zM7 16h2v2H7zM15 16h2v2h-2zM9 18h2v2H9zM13 18h2v2h-2z"/>',
    // the Pixel games folder (groups/pixel-games.json): a pixel heart
    "pixel-games":
      '<path class="s" d="M6 6h4v2H6zM14 6h4v2H14zM4 8h16v2H4zM4 10h16v2H4zM6 12h12v2H6zM8 14h8v2H8zM10 16h4v2H10z"/>' +
      '<path fill="#fff" fill-opacity=".45" stroke="none" d="M6 8h2v2H6z"/>',
    // the power symbol
    power:
      '<circle class="d" cx="12" cy="12.5" r="9"/>' +
      '<path d="M7.2 6.2a8 8 0 1 0 9.6 0" stroke-width="2.2"/><path d="M12 2.5v9" stroke-width="2.2"/>',
    // a print nozzle over a part it is building
    printforge:
      '<path d="M3 3.5h18M7 3.5V6M17 3.5V6" stroke-opacity=".55"/>' +
      '<path class="s" d="M9.5 5.5h5v3L12 11.2 9.5 8.5z"/>' +
      '<path class="d" d="M12 13.2l7.5 3.4L12 20l-7.5-3.4z"/>' +
      '<path d="M12 13.2l7.5 3.4V19L12 22.4 4.5 19v-2.4zM4.5 16.6L12 20l7.5-3.4M12 20v2.4"/>',
    // a speech card holding a {{variable}}'s braces
    prompts:
      '<path class="d" d="M3 5.5a2.5 2.5 0 0 1 2.5-2.5h13A2.5 2.5 0 0 1 21 5.5v9a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A2.5 2.5 0 0 1 3 14.5z"/>' +
      '<path d="M3 5.5a2.5 2.5 0 0 1 2.5-2.5h13A2.5 2.5 0 0 1 21 5.5v9a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A2.5 2.5 0 0 1 3 14.5z"/>' +
      '<path d="M10 6.5c-1.3 0-1.6.6-1.6 1.6v.6c0 .8-.4 1.3-1.2 1.3.8 0 1.2.5 1.2 1.3v.6c0 1 .3 1.6 1.6 1.6M14 6.5c1.3 0 1.6.6 1.6 1.6v.6c0 .8.4 1.3 1.2 1.3-.8 0-1.2.5-1.2 1.3v.6c0 1-.3 1.6-1.6 1.6" stroke-width="1.6"/>',
    // a sound wave with visualiser bars
    pulseforge:
      '<path class="s" d="M3 13h2v6H3zM19 10h2v9h-2z"/>' +
      '<path d="M2 9.5h3l2.2-5 3.6 15L14 5l2.2 7H22" stroke-width="2"/>',
    // a paper plane on its way
    relay:
      '<path class="d" d="M21.5 2.5l-19 7.6 7.2 3.4 3.4 7.2z"/>' +
      '<path d="M21.5 2.5l-19 7.6 7.2 3.4 3.4 7.2zM21.5 2.5l-11.8 11"/>',
    // a gear
    settings:
      '<path class="d" d="M20.44 10.36 L20.44 13.64 L18.34 13.82 L17.77 15.20 L19.13 16.81 L16.81 19.13 L15.20 17.77 L13.82 18.34 L13.64 20.44 L10.36 20.44 L10.18 18.34 L8.80 17.77 L7.19 19.13 L4.87 16.81 L6.23 15.20 L5.66 13.82 L3.56 13.64 L3.56 10.36 L5.66 10.18 L6.23 8.80 L4.87 7.19 L7.19 4.87 L8.80 6.23 L10.18 5.66 L10.36 3.56 L13.64 3.56 L13.82 5.66 L15.20 6.23 L16.81 4.87 L19.13 7.19 L17.77 8.80 L18.34 10.18Z"/>' +
      '<path d="M20.44 10.36 L20.44 13.64 L18.34 13.82 L17.77 15.20 L19.13 16.81 L16.81 19.13 L15.20 17.77 L13.82 18.34 L13.64 20.44 L10.36 20.44 L10.18 18.34 L8.80 17.77 L7.19 19.13 L4.87 16.81 L6.23 15.20 L5.66 13.82 L3.56 13.64 L3.56 10.36 L5.66 10.18 L6.23 8.80 L4.87 7.19 L7.19 4.87 L8.80 6.23 L10.18 5.66 L10.36 3.56 L13.64 3.56 L13.82 5.66 L15.20 6.23 L16.81 4.87 L19.13 7.19 L17.77 8.80 L18.34 10.18Z"/>' +
      '<circle cx="12" cy="12" r="3"/>',
    // a mortarboard
    "study-companion":
      '<path class="d" d="M12 4L1.5 9 12 14l10.5-5z"/>' +
      '<path d="M12 4L1.5 9 12 14l10.5-5zM6 11.2V16c1.6 1.6 3.6 2.4 6 2.4s4.4-.8 6-2.4v-4.8M22.5 9v6"/>',
    // a terminal prompt
    terminal:
      '<rect class="d" x="2" y="4" width="20" height="16" rx="2.5"/>' +
      '<rect x="2" y="4" width="20" height="16" rx="2.5"/><path d="M6 9.5l3 2.5-3 2.5M11.5 15H17"/>',
    // a page with a big serif T and lines of type
    typeset:
      '<path class="d" d="M6 2.5h8.5L19 7v12.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2z"/>' +
      '<path d="M6 2.5h8.5L19 7v12.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-15a2 2 0 0 1 2-2zM14.5 2.5V7H19"/>' +
      '<path d="M7.5 8h5M10 8v6M8.8 14h2.4M7.5 17.5h8M13.5 11h2"/>',
    // two pictures, one stacked on the other
    wallpapers:
      '<path d="M6.5 3h12A2.5 2.5 0 0 1 21 5.5v10" stroke-opacity=".55"/>' +
      '<rect class="d" x="3" y="6.5" width="14.5" height="14" rx="2.5"/><rect x="3" y="6.5" width="14.5" height="14" rx="2.5"/>' +
      '<path d="M3.5 18l4-4.5 3 3 2-2 4.5 4.5"/><circle class="s" cx="13" cy="10.5" r="1.4"/>',
    // a clipboard with its clip and a few lines
    clipboard:
      '<rect class="d" x="5" y="4" width="14" height="17.5" rx="2.5"/>' +
      '<rect x="5" y="4" width="14" height="17.5" rx="2.5"/><rect x="9" y="2.5" width="6" height="3.5" rx="1.2"/>' +
      '<path d="M8.5 11h7M8.5 14.5h7M8.5 18h4"/>',
    // a treemap: one square split into blocks by size
    disk:
      '<rect class="d" x="3" y="3" width="10" height="11" rx="2.5"/>' +
      '<rect x="3" y="3" width="18" height="18" rx="2.5"/><path d="M13 3v18M3 14h10M13 10h8M17 10v11"/>',
    // a page of log lines, one of them flagged
    logs:
      '<rect class="d" x="4" y="2.5" width="16" height="19" rx="2.5"/>' +
      '<rect x="4" y="2.5" width="16" height="19" rx="2.5"/><path d="M8 7.5h8M8 11h5M8 14.5h8M8 18h4"/>' +
      '<circle class="s" cx="16.5" cy="11" r="1.3"/>',
    // a step sequencer grid, some steps lit
    loops:
      '<rect class="d" x="2.5" y="4" width="19" height="16" rx="2.5"/>' +
      '<rect x="2.5" y="4" width="19" height="16" rx="2.5"/><path d="M7.25 4v16M12 4v16M16.75 4v16M2.5 9.33h19M2.5 14.67h19"/>' +
      '<g class="s"><rect x="3.4" y="4.9" width="2.9" height="3.5" rx=".6"/><rect x="12.9" y="4.9" width="2.9" height="3.5" rx=".6"/><rect x="8.15" y="10.25" width="2.9" height="3.5" rx=".6"/><rect x="3.4" y="15.6" width="2.9" height="3.5" rx=".6"/><rect x="17.65" y="15.6" width="2.9" height="3.5" rx=".6"/></g>',
    // a phone, its camera dot and home bar
    phone:
      '<rect class="d" x="6" y="2.5" width="12" height="19" rx="2.5"/>' +
      '<rect x="6" y="2.5" width="12" height="19" rx="2.5"/><path d="M10.5 18.5h3"/><circle class="s" cx="12" cy="5.8" r=".9"/>',
    // two papers, the front one marked new with a dot
    papers:
      '<rect class="d" x="7" y="2.5" width="13" height="16" rx="1.5"/>' +
      '<path d="M7 5.5V4a1.5 1.5 0 0 1 1.5-1.5h10A1.5 1.5 0 0 1 20 4v13a1.5 1.5 0 0 1-1.5 1.5H17"/>' +
      '<rect x="4" y="5.5" width="13" height="16" rx="1.5"/><path d="M7 10h7M7 13.5h7M7 17h4"/>' +
      '<circle class="s" cx="14" cy="17.5" r="1.3"/>',
    // a flashcard on its deck, an arrow bringing it back round
    recall:
      '<rect class="d" x="3" y="6" width="15" height="10" rx="1.5"/>' +
      '<path d="M7 3h12.5A1.5 1.5 0 0 1 21 4.5V12"/><rect x="3" y="6" width="15" height="10" rx="1.5"/><path d="M6.5 11h8"/>' +
      '<path d="M21 15.5a5 5 0 0 1-5 5H8.5M11 18l-2.5 2.5L11 23"/>',
    // books standing on a shelf, the last one leaning
    shelf:
      '<rect class="d" x="4" y="5" width="4" height="16" rx="1"/>' +
      '<path d="M2.5 21h19"/><rect x="4" y="5" width="4" height="16" rx="1"/><rect x="9.5" y="3" width="4" height="18" rx="1"/>' +
      '<path d="M15.2 7.6l3.8-1 3.4 13.4-3.8 1z"/>',
    // the corners of a screen grab around a lens
    snap:
      '<rect class="d" x="7" y="7" width="10" height="10" rx="1.5"/>' +
      '<path d="M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3"/>' +
      '<circle cx="12" cy="12" r="2.8"/>',
    // a knight on a board square
    gambit:
      '<path class="d" d="M7 20h11v-2.2c0-3.6-1.2-6.6-1.9-9.4C15.6 6.2 14 4.5 11.5 4l-.7-1.5-1 2.1C7.6 5.6 6 7.7 5.3 10.4l1.4 1.3 2.6-1.2.7 1.6C8.3 13.6 7 15.5 7 17.8z"/>' +
      '<path d="M7 20h11v-2.2c0-3.6-1.2-6.6-1.9-9.4C15.6 6.2 14 4.5 11.5 4l-.7-1.5-1 2.1C7.6 5.6 6 7.7 5.3 10.4l1.4 1.3 2.6-1.2.7 1.6C8.3 13.6 7 15.5 7 17.8zM5 21.5h15"/>' +
      '<circle cx="11.2" cy="7.6" r=".6"/>',
    tavern:
      '<path class="d" d="M12 2.5l8.5 4.8v9.4L12 21.5l-8.5-4.8V7.3z"/>' +
      '<path d="M12 2.5l8.5 4.8v9.4L12 21.5l-8.5-4.8V7.3zM12 7l4.5 8h-9zM12 2.5V7M20.5 7.3L16.5 15M3.5 7.3L7.5 15M7.5 15l-4 1.7M16.5 15l4 1.7M7.5 15L12 21.5l4.5-6.5"/>',
    // one keycap pressed fast, speed lines behind it
    typing:
      '<rect class="d" x="2.5" y="4.5" width="14" height="15" rx="2.2"/>' +
      '<rect x="2.5" y="4.5" width="14" height="15" rx="2.2"/><rect x="5" y="6.5" width="9" height="9" rx="1.2"/>' +
      '<path d="M18.5 8h3M19.5 12h2M18.5 16h3"/>',
    // a flame over a dumbbell bar
    reps:
      '<path class="d" d="M12 2.5c.6 2.6 3.8 4.4 3.8 8a3.8 3.8 0 0 1-7.6 0c0-1.7.9-2.8 1.8-3.6.2 1.3.8 2 1.6 2.3-.4-2.4.1-4.7.4-6.7z"/>' +
      '<path d="M12 2.5c.6 2.6 3.8 4.4 3.8 8a3.8 3.8 0 0 1-7.6 0c0-1.7.9-2.8 1.8-3.6.2 1.3.8 2 1.6 2.3-.4-2.4.1-4.7.4-6.7zM3 18.5h18"/>' +
      '<rect x="4.5" y="16" width="2.5" height="5" rx=".8"/><rect x="17" y="16" width="2.5" height="5" rx=".8"/>',
    // an hourglass, sand falling into the lower bulb
    focus:
      '<path class="d" d="M8 18.5c0-2 1.8-3 4-4.2 2.2 1.2 4 2.2 4 4.2z"/>' +
      '<path d="M5.5 2.5h13M5.5 21.5h13M7 2.5c0 4.6 5 6.5 5 9.5s-5 4.9-5 9.5M17 2.5c0 4.6-5 6.5-5 9.5s5 4.9 5 9.5M12 12v6"/>' +
      '<path d="M9.4 6.5h5.2"/>',
    // a chest with a cube resting on its lid
    vault:
      '<rect class="d" x="3" y="12" width="18" height="9" rx="1.5"/>' +
      '<rect x="3" y="12" width="18" height="9" rx="1.5"/><path d="M3 15.5h18M10.5 15.5v2.5h3v-2.5"/>' +
      '<path d="M12 2.5l4.2 2.1v4.3L12 11 7.8 8.9V4.6zM7.8 4.6L12 6.7l4.2-2.1M12 6.7V11"/>',
    // --- Forge apps added since the glyphs (2026-10-28)
    // a podcast mark: a dot on a stand with broadcast rings round it
    castforge:
      '<rect class="d" x="10.4" y="14.5" width="3.2" height="7" rx="1.6"/>' +
      '<rect x="10.4" y="14.5" width="3.2" height="7" rx="1.6"/>' +
      '<circle class="s" cx="12" cy="10.5" r="2.1"/>' +
      '<path d="M8.75 13.75A4.6 4.6 0 1 1 15.25 13.75M6.34 16.16A8 8 0 1 1 17.66 16.16"/>',
    // a test tube half full, with a spark of AI beside it
    modellab:
      '<path class="d" d="M6 11h5v6.5a2.5 2.5 0 0 1-5 0z"/>' +
      '<path d="M4.5 2.5h8M6 2.5v15a2.5 2.5 0 0 0 5 0v-15M6 11h5"/>' +
      '<path class="s" d="M16.5 7l1.2 3 3 1.2-3 1.2-1.2 3-1.2-3-3-1.2 3-1.2z"/>' +
      '<circle class="s" cx="18.8" cy="3.8" r="1"/>',
    // a chip: the model, with its pins
    "forge-models":
      '<rect class="d" x="6" y="6" width="12" height="12" rx="2"/>' +
      '<rect x="6" y="6" width="12" height="12" rx="2"/>' +
      '<path d="M9.5 2.5V6M14.5 2.5V6M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>' +
      '<rect class="s" x="9.5" y="9.5" width="5" height="5" rx="1"/>',
    // a magnifying glass over lines of writing
    librarian:
      '<circle class="d" cx="10" cy="10" r="6.8"/><circle cx="10" cy="10" r="6.8"/>' +
      '<path d="M15 15l6 6" stroke-width="2.4"/>' +
      '<path d="M6.8 8h6.4M6.8 10.7h6.4M6.8 13.4h3.6" stroke-width="1.4"/>',
    // scissors cutting
    cutroom:
      '<circle class="d" cx="6" cy="6" r="3"/><circle class="d" cx="6" cy="18" r="3"/>' +
      '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>' +
      '<path d="M20.5 4L8.2 15.8M14.5 14.5L20.5 20M8.2 8.2L12 12"/>',
    // a monitor showing a padlock (lock screen and login)
    setups:
      '<rect class="d" x="2.5" y="3.5" width="19" height="13" rx="2"/>' +
      '<rect x="2.5" y="3.5" width="19" height="13" rx="2"/><path d="M12 16.5v4M8 20.5h8"/>' +
      '<rect class="s" x="9.3" y="9.3" width="5.4" height="4.4" rx="1"/>' +
      '<path d="M10.4 9.3V8a1.6 1.6 0 0 1 3.2 0v1.3" stroke-width="1.5"/>',
    // two beamed music notes and an AI spark
    suno:
      '<circle class="s" cx="7" cy="17.5" r="2.6"/><circle class="s" cx="17" cy="15.5" r="2.6"/>' +
      '<path d="M9.6 17.5V7l10-2v10.5M9.6 10l10-2"/>' +
      '<path class="s" d="M4.5 2.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    // a shopping bag with a download arrow
    store:
      '<path class="d" d="M4.5 8h15l-1 12.5a1.5 1.5 0 0 1-1.5 1.4H7a1.5 1.5 0 0 1-1.5-1.4z"/>' +
      '<path d="M4.5 8h15l-1 12.5a1.5 1.5 0 0 1-1.5 1.4H7a1.5 1.5 0 0 1-1.5-1.4zM8.8 8V6.2a3.2 3.2 0 0 1 6.4 0V8"/>' +
      '<path d="M12 11v6.5M9.5 15l2.5 2.5 2.5-2.5"/>',
    // two crossed swords
    arena:
      '<path d="M20.5 3.5L8 16M3.5 3.5L16 16" stroke-width="2.2"/>' +
      '<path d="M5.3 13.3l5.4 5.4M18.7 13.3l-5.4 5.4M8 16l-3 3M16 16l3 3"/>' +
      '<circle class="s" cx="4.2" cy="19.8" r="1.5"/><circle class="s" cx="19.8" cy="19.8" r="1.5"/>',
    // a dial gauge, the needle well up
    gauge:
      '<path class="d" d="M4.2 17.5A9 9 0 1 1 19.8 17.5z"/>' +
      '<path d="M4.2 17.5A9 9 0 1 1 19.8 17.5M7 21h10"/>' +
      '<path d="M5.5 13h1.8M7.4 8.4l1.3 1.3M12 6v1.8" stroke-width="1.5"/>' +
      '<path d="M12 13l4.6-4.6"/><circle class="s" cx="12" cy="13" r="1.9"/>',
    // a word card with a kanji on it (bun, writing)
    kotoba:
      '<rect class="d" x="3.5" y="2.5" width="17" height="19" rx="2.5"/>' +
      '<rect x="3.5" y="2.5" width="17" height="19" rx="2.5"/>' +
      '<path d="M12 5v1.7M7.2 8.7h9.6M15 8.7C13.9 13.6 11.3 16.9 7.5 18.5M9 8.7c1.1 4.9 3.7 8.2 7.5 9.8" stroke-width="1.7"/>',
    // a round chat bubble with a plug in it
    switchboard:
      '<path class="d" d="M5.14 15.75A8.5 8.5 0 1 1 8.91 19.2L3.5 21z"/>' +
      '<path d="M5.14 15.75A8.5 8.5 0 1 1 8.91 19.2L3.5 21z"/>' +
      '<path d="M10.8 6.8v2.4M14.2 6.8v2.4M12.5 15v2.5"/>' +
      '<path class="s" d="M9 9.2h7v2.3a3.5 3.5 0 0 1-7 0z"/>',
    // a clock with an arrow winding it back (restore a snapshot)
    backup:
      '<circle class="d" cx="12" cy="12" r="9"/>' +
      '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8M3 3v5h5M12 7.5V12l3.5 2"/>',
    // a story scroll with a heart on it
    taleforge:
      '<path class="d" d="M4 3h13a2 2 0 0 1 2 2v12h-8a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 0 0-2-2z"/>' +
      '<path d="M19 17V5a2 2 0 0 0-2-2H4M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"/>' +
      '<path class="s" d="M12.5 14c-2.8-1.9-4-3.3-4-4.8a2 2 0 0 1 4-.4 2 2 0 0 1 4 .4c0 1.5-1.2 2.9-4 4.8z"/>',
    // a briefcase
    office:
      '<rect class="d" x="2.5" y="7" width="19" height="13.5" rx="2.5"/>' +
      '<rect x="2.5" y="7" width="19" height="13.5" rx="2.5"/>' +
      '<path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M2.5 12.5h19"/>' +
      '<rect class="s" x="10.3" y="11" width="3.4" height="3.4" rx=".8"/>',
    // a teacher beside a board
    tutor:
      '<rect class="d" x="2.5" y="3" width="12.5" height="10" rx="1.5"/>' +
      '<rect x="2.5" y="3" width="12.5" height="10" rx="1.5"/>' +
      '<path d="M5.5 9.8l2-2.2 2 1.5 2.7-3" stroke-width="1.5"/>' +
      '<circle cx="18" cy="13.2" r="2.3"/><path d="M14 21.5a4 4 0 0 1 8 0"/>',
    // a closed book with a cross on its cover
    bible:
      '<path class="d" d="M4.5 19V5A2.5 2.5 0 0 1 7 2.5h12.5v14H7A2.5 2.5 0 0 0 4.5 19z"/>' +
      '<path d="M4.5 19V5A2.5 2.5 0 0 1 7 2.5h12.5v19H7a2.5 2.5 0 0 1 0-5h12.5"/>' +
      '<path d="M12 5.2v8.3M9 8.3h6" stroke-width="2"/>',
    // a lit candle giving off light
    devotion:
      '<rect class="d" x="9" y="11" width="6" height="10.5" rx="1"/>' +
      '<rect x="9" y="11" width="6" height="10.5" rx="1"/><path d="M12 11V9.4"/>' +
      '<path class="s" d="M12 2.5c1.4 1.6 2.2 2.8 2.2 4a2.2 2.2 0 0 1-4.4 0c0-1.2.8-2.4 2.2-4z"/>' +
      '<path d="M5.5 4.5l1.6 1.2M18.5 4.5l-1.6 1.2M4.5 9.5h2M19.5 9.5h-2" stroke-width="1.5"/>',
    // a worker's hard hat
    workers:
      '<path class="d" d="M4.5 15v-1a7.5 7.5 0 0 1 15 0v1z"/>' +
      '<path d="M4.5 15v-1a7.5 7.5 0 0 1 15 0v1M10 7v5M14 7v5"/>' +
      '<rect x="2" y="15" width="20" height="3.5" rx="1.75"/>',
    // a microphone on its stand
    voice:
      '<rect class="d" x="8.5" y="2.5" width="7" height="11.5" rx="3.5"/>' +
      '<rect x="8.5" y="2.5" width="7" height="11.5" rx="3.5"/>' +
      '<path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v4M8.5 21.5h7"/>',
    // an envelope with a coin going in
    budget:
      '<path class="s" d="M7.5 8.5a4.5 4.5 0 0 1 9 0z"/>' +
      '<rect class="d" x="3" y="8.5" width="18" height="12" rx="2"/>' +
      '<rect x="3" y="8.5" width="18" height="12" rx="2"/><path d="M3.5 9.5L12 15l8.5-5.5"/>',
    // a cooking pot with steam rising
    recipes:
      '<path class="d" d="M4 12h16v4.5a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4z"/>' +
      '<path d="M4 12h16v4.5a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4zM2 12h20M2.5 14.5H4M20 14.5h1.5"/>' +
      '<path d="M8.5 9c-.8-1 .8-2 0-3.2M12 9c-.8-1 .8-2 0-3.2M15.5 9c-.8-1 .8-2 0-3.2" stroke-width="1.5"/>',
    // a house with a packed box inside
    homebox:
      '<path class="d" d="M3.5 10.5L12 3.5l8.5 7V20a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 20z"/>' +
      '<path d="M3.5 10.5L12 3.5l8.5 7V20a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 20z"/>' +
      '<rect x="8" y="12" width="8" height="6.5" rx="1"/><path d="M8 14.5h8M12 12v2.5"/>',
    // an iPod: screen above the click wheel
    ipod:
      '<rect class="d" x="5.5" y="2" width="13" height="20" rx="2.5"/>' +
      '<rect x="5.5" y="2" width="13" height="20" rx="2.5"/>' +
      '<rect x="8" y="4.5" width="8" height="6" rx="1"/>' +
      '<circle cx="12" cy="16" r="3.6"/><circle class="s" cx="12" cy="16" r="1.2"/>',
    // --- apps the Store installs (apps/store/catalog/<id>.json)
    // a page cut along a dashed line, its lower piece pulled aside
    bentopdf:
      '<path class="d" d="M3 10.5V4.5a2 2 0 0 1 2-2h7L16.5 7v3.5z"/>' +
      '<path d="M3 10.5V4.5a2 2 0 0 1 2-2h7L16.5 7v3.5M12 2.5V7h4.5M7.5 15.5v4a2 2 0 0 0 2 2H19a2 2 0 0 0 2-2v-4"/>' +
      '<path d="M3 13h18" stroke-width="1.4" stroke-dasharray="1.6 2.2"/>',
    // a rough hand-drawn box, a wobbly arrow, a rough circle
    excalidraw:
      '<path class="d" d="M4 4.2c3-.5 6.2-.4 9 0 .3 2.6.3 5 0 7.6-3 .4-6 .4-9 0-.3-2.5-.3-5 0-7.6z"/>' +
      '<path d="M2.8 4.3c3.4-.6 7-.5 10.6 0M4 3c-.5 3.1-.4 6.2.2 9.2M2.8 11.7c3.4.4 7 .3 10.6-.2M12.9 3.2c.5 3 .5 6 .1 9.3"/>' +
      '<path d="M7.5 14c-.2 3 1.2 4.6 4.2 4.6M9.6 16.4l2.2 2.2-2.3 2M17.2 13.2c2.6-.1 4.4 1.4 4.3 3.9-.1 2.6-2.2 4.3-4.6 4.2-2.3-.1-3.8-1.9-3.6-4.2.2-2.3 1.8-3.7 4.4-3.9.6 0 1.1.1 1.6.3"/>',
    // a closed reference book with a globe on its cover
    kiwix:
      '<path class="d" d="M5 19.5V4.5a2 2 0 0 1 2-2h12v15H7a2 2 0 0 0-2 2z"/>' +
      '<path d="M5 19.5V4.5a2 2 0 0 1 2-2h12v15H7a2 2 0 0 0-2 2 2 2 0 0 0 2 2h12v-4"/>' +
      '<circle cx="12" cy="10" r="4.2" stroke-width="1.5"/><path d="M7.8 10h8.4M12 5.8c-1.9 2.5-1.9 5.9 0 8.4 1.9-2.5 1.9-5.9 0-8.4z" stroke-width="1.3"/>',
    // a game cartridge with its label and grip lines
    retro:
      '<path class="d" d="M7.5 5h9v7.5h-9z"/>' +
      '<path d="M4.5 4A1.5 1.5 0 0 1 6 2.5h12A1.5 1.5 0 0 1 19.5 4v14.5l-2 1.5v1.5h-11V20l-2-1.5z"/>' +
      '<rect x="7.5" y="5" width="9" height="7.5" rx="1"/><path d="M9 16v2.2M12 16v2.2M15 16v2.2" stroke-width="1.5"/>',
    // the feed symbol: a dot and two widening waves
    yarr:
      '<rect class="d" x="3" y="3" width="18" height="18" rx="4"/>' +
      '<rect x="3" y="3" width="18" height="18" rx="4"/>' +
      '<path d="M7.5 11.5a5 5 0 0 1 5 5M7.5 7a9.5 9.5 0 0 1 9.5 9.5"/><circle class="s" cx="8" cy="16" r="1.6"/>',
    // a magnifying glass over three linked sources
    searxng:
      '<circle class="d" cx="10" cy="10" r="7"/><circle cx="10" cy="10" r="7"/>' +
      '<path d="M15.2 15.2l5.8 5.8" stroke-width="2.4"/>' +
      '<path d="M10 7l-2.8 4.6h5.6z" stroke-width="1"/>' +
      '<circle class="s" cx="10" cy="7" r="1.5"/><circle class="s" cx="7.2" cy="11.6" r="1.5"/><circle class="s" cx="12.8" cy="11.6" r="1.5"/>',
    // a web page with an eye keeping watch on it
    watch:
      '<path class="d" d="M5 3.5h14A2.5 2.5 0 0 1 21.5 6v2h-19V6A2.5 2.5 0 0 1 5 3.5z"/>' +
      '<rect x="2.5" y="3.5" width="19" height="17" rx="2.5"/><path d="M2.5 8h19"/>' +
      '<path d="M5.8 14.4c3.4-4.4 9-4.4 12.4 0-3.4 4.4-9 4.4-12.4 0z"/><circle class="s" cx="12" cy="14.4" r="1.7"/>',
    // a bookmark ribbon with a tag hung on it
    linkding:
      '<path class="d" d="M4 2.5h9v17.5l-4.5-3.6L4 20z"/>' +
      '<path d="M4 2.5h9v10M4 2.5V20l4.5-3.6 3.5 2.8"/>' +
      '<path d="M13 12.5h5l3.5 3.8-3.5 3.7h-5a1 1 0 0 1-1-1v-5.5a1 1 0 0 1 1-1z"/><circle class="s" cx="14.8" cy="16.3" r="1.2"/>',
    // a page, picture above the scan line, text lines below
    ocr:
      '<path class="d" d="M6 2.5h12a2 2 0 0 1 2 2v7.5H4V4.5a2 2 0 0 1 2-2z"/>' +
      '<rect x="4" y="2.5" width="16" height="19" rx="2"/>' +
      '<path d="M6.5 10l3-3 2.2 2.2 1.6-1.6 2.2 2.4M1.8 12.8h20.4M8 16.3h8M8 19h5"/><circle class="s" cx="15.6" cy="6" r="1.1"/>',
    // two code cells, each with its run arrow
    notebook:
      '<rect class="d" x="8" y="3" width="13.5" height="7.5" rx="1.8"/>' +
      '<rect x="8" y="3" width="13.5" height="7.5" rx="1.8"/><rect x="8" y="13.5" width="13.5" height="7.5" rx="1.8"/>' +
      '<path class="s" d="M2.5 4.8v3.9l3.3-1.95zM2.5 15.3v3.9l3.3-1.95z"/><path d="M11 17.25h7.5" stroke-width="1.5"/>',
    // a folder with sync arrows going round
    syncthing:
      '<path class="d" d="M2.5 8h19v10a2.5 2.5 0 0 1-2.5 2.5H5A2.5 2.5 0 0 1 2.5 18z"/>' +
      '<path d="M2.5 18V6A2.5 2.5 0 0 1 5 3.5h4l2.2 2.5H19A2.5 2.5 0 0 1 21.5 8.5V18a2.5 2.5 0 0 1-2.5 2.5H5A2.5 2.5 0 0 1 2.5 18z"/>' +
      '<path d="M8 13.4a4 4 0 0 1 6.6-2.3M16 15.6a4 4 0 0 1-6.6 2.3" stroke-width="1.6"/>' +
      '<path class="s" d="M16.4 9.4l.2 3.6-3.5-.7zM7.6 19.6l-.2-3.6 3.5.7z"/>',
    // a calendar with a two-way arrow across it
    radicale:
      '<path class="d" d="M6 5h12a2.5 2.5 0 0 1 2.5 2.5V10h-17V7.5A2.5 2.5 0 0 1 6 5z"/>' +
      '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/>' +
      '<path d="M3.5 10h17M8 3v4M16 3v4M7 13.5h9M8 17.5h9"/>' +
      '<path class="s" d="M15.6 11.3l2.6 2.2-2.6 2.2zM8.4 15.3l-2.6 2.2 2.6 2.2z"/>',
    // a panel of live readings: a pulse line over three bars
    glances:
      '<rect class="d" x="2.5" y="3.5" width="19" height="17" rx="2.5"/>' +
      '<rect x="2.5" y="3.5" width="19" height="17" rx="2.5"/>' +
      '<path d="M5.5 10h3l1.5-3 2 5 1.5-2h5"/>' +
      '<path class="s" d="M6 14.5h2.4v3.5H6zM10.8 13.5h2.4V18h-2.4zM15.6 15.5H18V18h-2.4z"/>',
    // a note page with a chain link on its corner
    silverbullet:
      '<path class="d" d="M5 2.5h11a2 2 0 0 1 2 2V11h-6.5v8H5a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2z"/>' +
      '<path d="M11 19H5a2 2 0 0 1-2-2V4.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2V10M6.5 7h8M6.5 10.5h5M6.5 14h3"/>' +
      '<path d="M15.8 13.6l1.4-1.4a2.6 2.6 0 0 1 3.7 3.7l-1.4 1.4M17.2 20.2l-1.4 1.4a2.6 2.6 0 0 1-3.7-3.7l1.4-1.4M15.3 18.5l3-3"/>',
    // a bell with a small arrow coming in
    ntfy:
      '<path class="d" d="M5 17v-5.5a6 6 0 0 1 12 0V17l1.6 1.8H3.4z"/>' +
      '<path d="M5 17v-5.5a6 6 0 0 1 12 0V17l1.6 1.8H3.4zM9 21.5h4"/>' +
      '<path d="M21.5 2.5l-4.2 4.2M17.3 3.5v3.2h3.2"/>',
    // a wrench crossed with a screwdriver
    "it-tools":
      '<path class="d" d="M15 3.2a4.6 4.6 0 0 0-4.4 6.1l-7 7a2 2 0 0 0 2.8 2.8l7-7a4.6 4.6 0 0 0 6.1-4.4l-2.8 2.8-2.6-.6-.6-2.6z"/>' +
      '<path d="M15 3.2a4.6 4.6 0 0 0-4.4 6.1l-7 7a2 2 0 0 0 2.8 2.8l7-7a4.6 4.6 0 0 0 6.1-4.4l-2.8 2.8-2.6-.6-.6-2.6z"/>' +
      '<path d="M3 3l1.5 1 6.2 6.2M14.6 14.6l5.4 5.4a1.6 1.6 0 0 1-2.3 2.3l-5.4-5.4z"/>',
    // a flowchart: a box branching to a box and a decision diamond
    drawio:
      '<rect class="d" x="8" y="2.5" width="8" height="5.5" rx="1.2"/>' +
      '<rect x="8" y="2.5" width="8" height="5.5" rx="1.2"/>' +
      '<path d="M12 8v3M6 11h12M6 11v3.5M18 11v2.5M2.5 14.5h7v6h-7zM18 13.5l3.5 3.5-3.5 3.5-3.5-3.5z"/>',
    // a cube with its corner points marked, ready to model
    blockbench:
      '<path class="d" d="M12 3l8 4.5-8 4.5-8-4.5z"/>' +
      '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9"/>' +
      '<g class="s"><circle cx="12" cy="3" r="1.5"/><circle cx="4" cy="7.5" r="1.5"/><circle cx="20" cy="7.5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="4" cy="16.5" r="1.5"/><circle cx="20" cy="16.5" r="1.5"/><circle cx="12" cy="21" r="1.5"/></g>',
    // a painter's palette with dabs of paint
    paint:
      '<path class="d" d="M12 3a9 9 0 0 0 0 18c1.4 0 2-.9 2-1.9 0-1.4-1.2-1.8-1.2-3 0-1 .8-1.6 1.8-1.6H17a4 4 0 0 0 4-4C21 6.4 17 3 12 3z"/>' +
      '<path d="M12 3a9 9 0 0 0 0 18c1.4 0 2-.9 2-1.9 0-1.4-1.2-1.8-1.2-3 0-1 .8-1.6 1.8-1.6H17a4 4 0 0 0 4-4C21 6.4 17 3 12 3z"/>' +
      '<g class="s"><circle cx="7.5" cy="12.5" r="1.5"/><circle cx="8.5" cy="8" r="1.5"/><circle cx="12.8" cy="6.8" r="1.5"/><circle cx="16.8" cy="9.2" r="1.5"/></g>',
    // a model cut into stacked layers
    slicer:
      '<path class="d" d="M12 3l9 4.5-9 4.5-9-4.5z"/>' +
      '<path d="M12 3l9 4.5-9 4.5-9-4.5zM3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5"/>',
    // a chef's hat
    cyberchef:
      '<path class="d" d="M7 14.5a4 4 0 0 1-.7-7.9A5.8 5.8 0 0 1 12 3a5.8 5.8 0 0 1 5.7 3.6 4 4 0 0 1-.7 7.9V20.5H7z"/>' +
      '<path d="M7 14.5a4 4 0 0 1-.7-7.9A5.8 5.8 0 0 1 12 3a5.8 5.8 0 0 1 5.7 3.6 4 4 0 0 1-.7 7.9V20.5H7zM7 17.2h10M10 11.5v2.5M14 11.5v2.5"/>',
    // a record sliding out of its sleeve
    beets:
      '<path d="M13 6a6.5 6.5 0 1 1 0 12M13 9.55a3.5 3.5 0 1 1 0 4.9" />' +
      '<circle class="s" cx="15.5" cy="12" r="1.3"/>' +
      '<rect class="d" x="2.5" y="4" width="10.5" height="16" rx="1.5"/><rect x="2.5" y="4" width="10.5" height="16" rx="1.5"/>',
    // an ebook reader showing a page of text
    "calibre-web":
      '<rect x="4" y="2.5" width="16" height="19" rx="2.5"/>' +
      '<rect class="d" x="6.8" y="5.2" width="10.4" height="11.8" rx=".8"/>' +
      '<path d="M9 8.5h6M9 11h6M9 13.5h3.5M10.5 19h3" stroke-width="1.4"/>',
    // a lightning bolt with a spark beside it
    flash:
      '<path class="d" d="M13.5 2.5L5 13.5h6l-1.5 8 8.5-11h-6z"/>' +
      '<path d="M13.5 2.5L5 13.5h6l-1.5 8 8.5-11h-6z"/>' +
      '<path class="s" d="M19.5 15l.6 1.6 1.6.6-1.6.6-.6 1.6-.6-1.6-1.6-.6 1.6-.6z"/>',
    // --- groups (places): groups/<id>.json, or its "glyph" field
    // two little robot heads, one working in front of the other
    agents:
      '<rect class="d" x="9" y="9" width="12" height="11" rx="2.5"/>' +
      '<rect x="9" y="9" width="12" height="11" rx="2.5"/>' +
      '<path d="M15 9V6.5M9 12.5H5.5A2.5 2.5 0 0 1 3 10V6A2.5 2.5 0 0 1 5.5 3.5h4A2.5 2.5 0 0 1 12 6v3M13.5 17h3"/>' +
      '<circle class="s" cx="15" cy="5" r="1.3"/><circle class="s" cx="12.8" cy="13.6" r="1.3"/><circle class="s" cx="17.2" cy="13.6" r="1.3"/>' +
      '<circle class="s" cx="5.8" cy="7.6" r="1"/><circle class="s" cx="9" cy="7.6" r="1"/>',
    // a service bell on the desk, ready when called
    assistant:
      '<path class="d" d="M4 16.5a8 8 0 0 1 16 0z"/>' +
      '<path d="M4 16.5a8 8 0 0 1 16 0M12 8.5V6M10 5.5h4"/>' +
      '<rect x="2.5" y="16.5" width="19" height="3.5" rx="1.2"/>' +
      '<path d="M7.8 13.6a4.6 4.6 0 0 1 2.4-2.4" stroke-width="1.4"/>',
    // a drive inside two arrows going round (snapshots and sync)
    "backup-sync":
      '<path d="M20.5 12A8.5 8.5 0 0 1 6 18M9 18H6v3M3.5 12A8.5 8.5 0 0 1 18 6M15 6h3V3"/>' +
      '<path class="d" d="M8.5 9.5v5c0 .8 1.6 1.4 3.5 1.4s3.5-.6 3.5-1.4v-5z"/>' +
      '<ellipse cx="12" cy="9.5" rx="3.5" ry="1.4"/>' +
      '<path d="M8.5 9.5v5c0 .8 1.6 1.4 3.5 1.4s3.5-.6 3.5-1.4v-5"/>',
    // a lit oil lamp (a lamp unto my feet)
    "bible-today":
      '<path class="d" d="M3.5 14h12.5l4.5-2c-.3 1.8-1.8 3.4-3.6 4.1-1.4 2.2-4 3.4-7 3.4-3.6 0-5.9-2-6.4-5.5z"/>' +
      '<path d="M3.5 14h12.5l4.5-2c-.3 1.8-1.8 3.4-3.6 4.1-1.4 2.2-4 3.4-7 3.4-3.6 0-5.9-2-6.4-5.5zM8 21.5h6M3.8 15.5c-1.9-.2-2-2.8-.1-3"/>' +
      '<path class="s" d="M19.5 10.3c-1.4-1-2-2.3-1.6-3.6.4-1.3 1.4-2.2 1.6-4.2 1.2 1.4 2.4 3 2.1 4.6-.2 1.3-1 2.3-2.1 3.2z"/>',
    // a canvas on an easel with a brush stroke on it
    "create-art":
      '<rect class="d" x="3.5" y="5.5" width="17" height="10" rx="1.5"/>' +
      '<rect x="3.5" y="5.5" width="17" height="10" rx="1.5"/>' +
      '<path d="M12 2.5v3M8 15.5l-2.5 6M16 15.5l2.5 6M12 15.5v6"/>' +
      '<path d="M7 12.5c1.4-2.6 2.9-2.8 4.3-1s2.9 1.8 5.2-1.8" stroke-width="2"/>',
    // a phone with signal waves going out to it
    "devices-place":
      '<rect class="d" x="4" y="3" width="9" height="18" rx="2"/>' +
      '<rect x="4" y="3" width="9" height="18" rx="2"/><path d="M7.5 18h2"/>' +
      '<path d="M16 9.5a3.5 3.5 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10"/>',
    // a filing cabinet, three drawers
    "files-place":
      '<rect class="d" x="4.5" y="2.5" width="15" height="19" rx="2"/>' +
      '<rect x="4.5" y="2.5" width="15" height="19" rx="2"/>' +
      '<path d="M4.5 9h15M4.5 15h15M10.5 5.8h3M10.5 11.8h3M10.5 17.8h3"/>',
    // an apple for the teacher
    learn:
      '<path class="d" d="M12 8c-1.3-.9-3.2-1.3-4.8-.6C4.6 8.4 4 11.2 4.5 13.8c.7 3.7 3.1 7.2 5.4 7.2.9 0 1.4-.5 2.1-.5s1.2.5 2.1.5c2.3 0 4.7-3.5 5.4-7.2.5-2.6-.1-5.4-2.7-6.4-1.6-.7-3.5-.3-4.8.6z"/>' +
      '<path d="M12 8c-1.3-.9-3.2-1.3-4.8-.6C4.6 8.4 4 11.2 4.5 13.8c.7 3.7 3.1 7.2 5.4 7.2.9 0 1.4-.5 2.1-.5s1.2.5 2.1.5c2.3 0 4.7-3.5 5.4-7.2.5-2.6-.1-5.4-2.7-6.4-1.6-.7-3.5-.3-4.8.6zM12 8c0-1.8.4-3.4 1.6-4.8"/>' +
      '<path class="s" d="M14.2 5.6c.7-1.9 2.4-3 5-2.9-.6 2.4-2.4 3.4-5 2.9z"/>' +
      '<path d="M7.2 12a3.4 3.4 0 0 1 1.8-2" stroke-width="1.4"/>',
    // a library building: pediment, columns and steps
    library:
      '<path class="d" d="M2.5 8L12 3l9.5 5z"/>' +
      '<path d="M2.5 8L12 3l9.5 5zM5 8v10M9.7 8v10M14.3 8v10M19 8v10M3.5 18h17M2.5 21h19"/>',
    // a sprout with two leaves
    life:
      '<path class="d" d="M12 14c-4.5 0-7.5-2.5-7.5-6.5 4.5 0 7.5 2.5 7.5 6.5zM12 11.5c0-4 2.6-7 7.5-7 0 4-2.8 7-7.5 7z"/>' +
      '<path d="M12 14c-4.5 0-7.5-2.5-7.5-6.5 4.5 0 7.5 2.5 7.5 6.5zM12 11.5c0-4 2.6-7 7.5-7 0 4-2.8 7-7.5 7zM12 21.5V11.5M6 21.5h12"/>',
    // a cube with an orbit arrow turning it round
    "make-3d":
      '<path class="d" d="M12 8l6 3.2-6 3.2-6-3.2z"/>' +
      '<path d="M12 8l6 3.2v7L12 21.4l-6-3.2v-7zM6 11.2l6 3.2 6-3.2M12 14.4v7"/>' +
      '<path d="M3.5 7.9A9 9 0 0 1 20.5 7.9M21.6 5.4l-1.1 2.5-2.6-1.2"/>',
    // piano keys
    "make-music":
      '<rect class="d" x="2.5" y="4" width="19" height="16" rx="2"/>' +
      '<rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="M7.25 13.5V20M12 13.5V20M16.75 13.5V20"/>' +
      '<path class="s" d="M6 4h2.5v9.5H6zM10.75 4h2.5v9.5h-2.5zM15.5 4H18v9.5h-2.5z"/>',
    // a memory stick: chips on a board with pins
    "memory-disk":
      '<rect class="d" x="2" y="6.5" width="20" height="10" rx="1.5"/>' +
      '<rect x="2" y="6.5" width="20" height="10" rx="1.5"/>' +
      '<g class="s"><rect x="4.5" y="9" width="3.6" height="4.5" rx=".7"/><rect x="10.2" y="9" width="3.6" height="4.5" rx=".7"/><rect x="15.9" y="9" width="3.6" height="4.5" rx=".7"/></g>' +
      '<path d="M4.5 16.5v3M7 16.5v3M9.5 16.5v3M14.5 16.5v3M17 16.5v3M19.5 16.5v3"/>',
    // a small neural net: three layers of nodes
    models:
      '<path d="M4.5 7.5l7.5-3M4.5 7.5L12 12M4.5 16.5L12 12M4.5 16.5l7.5 3M12 4.5l7.5 3M12 12l7.5-4.5M12 12l7.5 4.5M12 19.5l7.5-3" stroke-width="1.4" stroke-opacity=".6"/>' +
      '<g class="s"><circle cx="4.5" cy="7.5" r="2.2"/><circle cx="4.5" cy="16.5" r="2.2"/><circle cx="12" cy="4.5" r="2.2"/><circle cx="12" cy="12" r="2.2"/><circle cx="12" cy="19.5" r="2.2"/><circle cx="19.5" cy="7.5" r="2.2"/><circle cx="19.5" cy="16.5" r="2.2"/></g>',
    // two stacks of coins and one more coin coming
    money:
      '<ellipse class="d" cx="6.8" cy="7.2" rx="4.3" ry="1.8"/><ellipse class="d" cx="17.2" cy="13.2" rx="4.3" ry="1.8"/>' +
      '<ellipse cx="6.8" cy="7.2" rx="4.3" ry="1.8"/><ellipse cx="17.2" cy="13.2" rx="4.3" ry="1.8"/>' +
      '<path d="M2.5 7.2v12c0 1 1.9 1.8 4.3 1.8s4.3-.8 4.3-1.8v-12M2.5 10.2c0 1 1.9 1.8 4.3 1.8s4.3-.8 4.3-1.8M2.5 13.2c0 1 1.9 1.8 4.3 1.8s4.3-.8 4.3-1.8M2.5 16.2c0 1 1.9 1.8 4.3 1.8s4.3-.8 4.3-1.8"/>' +
      '<path d="M12.9 13.2v6c0 1 1.9 1.8 4.3 1.8s4.3-.8 4.3-1.8v-6M12.9 16.2c0 1 1.9 1.8 4.3 1.8s4.3-.8 4.3-1.8"/>' +
      '<circle class="s" cx="17.2" cy="6.5" r="2.2"/>',
    // a play button with a music note beside it
    "music-video":
      '<circle class="d" cx="10" cy="13.5" r="7.8"/><circle cx="10" cy="13.5" r="7.8"/>' +
      '<path class="s" d="M8 10v7l5.8-3.5z"/>' +
      '<ellipse class="s" cx="19" cy="7.5" rx="1.9" ry="1.5"/><path d="M20.6 7V2.5l1.4 1.2"/>',
    // an office building, rows of windows and a door
    "office-place":
      '<path class="d" d="M5 21V5a1.5 1.5 0 0 1 1.5-1.5h11A1.5 1.5 0 0 1 19 5v16z"/>' +
      '<path d="M5 21V5a1.5 1.5 0 0 1 1.5-1.5h11A1.5 1.5 0 0 1 19 5v16M3 21h18M10.5 21v-3.5h3V21"/>' +
      '<path class="s" d="M8 7h2v2H8zM14 7h2v2h-2zM8 11.5h2v2H8zM14 11.5h2v2h-2z"/>',
    // a picture in a deep frame
    pictures:
      '<path class="d" fill-rule="evenodd" d="M4.5 3h15A2.5 2.5 0 0 1 22 5.5v13a2.5 2.5 0 0 1-2.5 2.5h-15A2.5 2.5 0 0 1 2 18.5v-13A2.5 2.5 0 0 1 4.5 3zM6 7v10h12V7z"/>' +
      '<rect x="2" y="3" width="20" height="18" rx="2.5"/><rect x="6" y="7" width="12" height="10" rx=".8"/>' +
      '<path d="M6.5 16.5l3.5-3.8 2.5 2.5 1.6-1.6 3.4 2.9" stroke-width="1.6"/><circle class="s" cx="14.8" cy="9.8" r="1.2"/>',
    // a tilted die showing five
    play:
      '<g transform="rotate(-12 12 12)"><rect class="d" x="4" y="4" width="16" height="16" rx="3.5"/>' +
      '<rect x="4" y="4" width="16" height="16" rx="3.5"/>' +
      '<g class="s"><circle cx="8.3" cy="8.3" r="1.5"/><circle cx="15.7" cy="8.3" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="8.3" cy="15.7" r="1.5"/><circle cx="15.7" cy="15.7" r="1.5"/></g></g>',
    // a magnifier over a little bar chart
    "research-place":
      '<circle class="d" cx="10" cy="10" r="6.8"/><circle cx="10" cy="10" r="6.8"/>' +
      '<path d="M15 15l5.5 5.5" stroke-width="2.4"/>' +
      '<path d="M7.3 12.6v-1.8M10 12.6V7.4M12.7 12.6V9.6" stroke-width="1.6"/>',
    // two switches, one on and one off
    "settings-place":
      '<rect class="d" x="2.5" y="3.5" width="19" height="7.5" rx="3.75"/>' +
      '<rect x="2.5" y="3.5" width="19" height="7.5" rx="3.75"/><rect x="2.5" y="13" width="19" height="7.5" rx="3.75"/>' +
      '<circle class="s" cx="17.75" cy="7.25" r="2.1"/><circle class="s" cx="6.25" cy="16.75" r="2.1"/>',
    // a window with a title bar, a prompt and a closing tag
    "terminal-code":
      '<rect class="d" x="2" y="3.5" width="20" height="17" rx="2.5"/>' +
      '<rect x="2" y="3.5" width="20" height="17" rx="2.5"/><path d="M2 8h20M6 11.5l3 2.5-3 2.5M11.5 17l2-6M15.5 11.5l3 2.5-3 2.5"/>' +
      '<g class="s"><circle cx="5" cy="5.75" r=".9"/><circle cx="7.6" cy="5.75" r=".9"/><circle cx="10.2" cy="5.75" r=".9"/></g>',
    // a quill standing in an ink pot
    write:
      '<path class="d" d="M9 14c1.2-5.2 5.6-10 12-11.5-.9 6-5.7 10.4-12 11.5z"/>' +
      '<path d="M9 14c1.2-5.2 5.6-10 12-11.5-.9 6-5.7 10.4-12 11.5zM8 15.5L17 6.5"/>' +
      '<path class="d" d="M4 21.5h9a1 1 0 0 0 1-1V18a2.5 2.5 0 0 0-2.5-2.5h-6A2.5 2.5 0 0 0 3 18v2.5a1 1 0 0 0 1 1z"/>' +
      '<path d="M4 21.5h9a1 1 0 0 0 1-1V18a2.5 2.5 0 0 0-2.5-2.5h-6A2.5 2.5 0 0 0 3 18v2.5a1 1 0 0 0 1 1z"/>',
    // --- more Forge apps
    // a project board: task cards in three columns, fewer as they move along
    enjoy:
      '<path class="d" d="M3 4h5v4H3zM3 10h5v4H3zM3 16h5v4H3zM9.5 4h5v4h-5zM9.5 10h5v4h-5z"/>' +
      '<rect x="3" y="4" width="5" height="4" rx="1"/><rect x="3" y="10" width="5" height="4" rx="1"/>' +
      '<rect x="3" y="16" width="5" height="4" rx="1"/><rect x="9.5" y="4" width="5" height="4" rx="1"/>' +
      '<rect x="9.5" y="10" width="5" height="4" rx="1"/><rect x="16" y="4" width="5" height="4" rx="1"/>' +
      '<path d="M17.3 6l.9.9 1.6-1.7"/>',
    // a laptop and a phone paired: one line joins them over the top
    devices:
      '<rect class="d" x="2.5" y="9" width="11" height="7.5" rx="1.5"/>' +
      '<rect x="2.5" y="9" width="11" height="7.5" rx="1.5"/><path d="M1.5 19.5h13"/>' +
      '<rect class="d" x="16" y="10" width="6" height="10.5" rx="1.5"/>' +
      '<rect x="16" y="10" width="6" height="10.5" rx="1.5"/>' +
      '<path d="M8 9V6.5a3 3 0 0 1 3-3h5a3 3 0 0 1 3 3V10"/><circle class="s" cx="19" cy="18" r=".8"/>',
  };

  // The classic emoji. Before the glyphs Jan Tune and Power were both ⚡,
  // Mission Control and Jan Hollow both 🛰️ (the owner asked for new ones for
  // Jan Tune and Mission Control), and five other pairs repeated; in each pair
  // the older app kept its emoji.
  const CLASSIC = {
    acchan: "🐱",
    afterglow: "✨",
    "ai-studio": "🎨",
    arcade: "🕹️",
    atlas: "🌏",
    board: "📌",
    browser: "🌐",
    calendar: "📅",
    claude: "✳️",
    clipboard: "📋",
    code: "🧩",
    "codec-lab": "🧪",
    "codec-player": "📺",
    comix: "📚",
    convert: "🔀",
    cosmos: "🪐",
    crewroom: "🛋️",
    disk: "🗺️",
    dossier: "🗂️",
    driftpeaks: "🏂",
    eightysix: "🦾",
    emberfield: "🔥",
    exolab: "🦿",
    files: "📁",
    foresight: "🔭",
    inkforge: "🖋️",
    "jan-tune": "🎛️",
    janhollow: "🛰️",
    keymap: "⌨️",
    logins: "🔑",
    logs: "📜",
    loops: "🥁",
    media: "🎧",
    mediaforge: "🎞️",
    mint: "🪙",
    mission: "🚀",
    novelforge: "📖",
    panelforge: "🎬",
    papers: "🔬",
    phone: "📱",
    "pixel-games": "🎮",
    pixelforge: "👾",
    power: "⚡",
    printforge: "🖨️",
    prompts: "✒️",
    pulseforge: "🎵",
    recall: "🧠",
    relay: "📨",
    settings: "⚙️",
    shelf: "🔖",
    snap: "📸",
    "study-companion": "🎓",
    terminal: "💻",
    typeset: "📃",
    trader: "📈",
    vault: "🗃️",
    gambit: "♟️",
    tavern: "🐉",
    typing: "🥋",
    reps: "💪",
    focus: "⏳",
    wallpapers: "🖼️",
    // added 2026-10-28 with their glyphs (apps, Store apps, groups)
    castforge: "📻",
    modellab: "🧫",
    "forge-models": "🦙",
    librarian: "📇",
    cutroom: "✂️",
    setups: "🔐",
    suno: "🎤",
    store: "🛍️",
    arena: "🏟️",
    gauge: "🌡️",
    kotoba: "🗾",
    switchboard: "🔌",
    backup: "💾",
    taleforge: "🧙",
    office: "💼",
    tutor: "🏫",
    bible: "✝️",
    workers: "🖥️",
    devotion: "🕯️",
    voice: "🎙️",
    ipod: "📀",
    budget: "🧾",
    recipes: "🍲",
    homebox: "📦",
    bentopdf: "📑",
    excalidraw: "✏️",
    kiwix: "🌍",
    retro: "📼",
    yarr: "📰",
    searxng: "🧭",
    watch: "👀",
    linkding: "🔗",
    ocr: "📠",
    notebook: "📓",
    syncthing: "🔄",
    radicale: "🗒️",
    glances: "🩺",
    silverbullet: "📝",
    ntfy: "🔔",
    "it-tools": "🧰",
    drawio: "📐",
    blockbench: "🧊",
    paint: "🖌️",
    slicer: "🍰",
    cyberchef: "🍳",
    beets: "🏷️",
    "calibre-web": "📘",
    flash: "💥",
    agents: "🐝",
    assistant: "💬",
    "backup-sync": "🛟",
    "bible-today": "⛪",
    "create-art": "🖍️",
    "devices-place": "📡",
    "files-place": "🗄️",
    learn: "🎒",
    library: "🏛️",
    life: "🌱",
    "make-3d": "🧱",
    "make-music": "🎹",
    "memory-disk": "📊",
    models: "🤖",
    money: "💰",
    "music-video": "🍿",
    "office-place": "🏢",
    pictures: "🏞️",
    play: "🎲",
    "research-place": "🔎",
    "settings-place": "🔧",
    "terminal-code": "🐚",
    write: "✍️",
    enjoy: "🎯",
    devices: "🤝",
  };

  const STYLES = ["new", "classic"];
  let current = "new";

  const MARKS = [
    [/class="d"/g, 'fill="currentColor" fill-opacity=".3" stroke="none"'],
    [/class="s"/g, 'fill="currentColor" stroke="none"'],
    [/class="c"/g, 'fill="#e8875f"'],
  ];

  function svg(id) {
    const body = GLYPHS[id];
    if (!body) return "";
    const inner = MARKS.reduce((s, [re, attrs]) => s.replace(re, attrs), body);
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" class="forge-glyph" viewBox="0 0 24 24" width="1em" height="1em" fill="none" ' +
      'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true">' +
      inner +
      "</svg>"
    );
  }

  // Each painted element remembers its app (data-icon) and fallback text, so
  // setStyle can repaint it in place. Only the icon is swapped: a dock item's
  // tooltip after it stays. Repainting the same glyph is skipped, so a status
  // refresh that calls this every few seconds does not rebuild the SVG.
  function paint(el, id, text) {
    const fallback = text == null ? "" : String(text);
    el.dataset.icon = id;
    el.dataset.iconText = fallback;
    const first = el.firstChild;
    const face =
      first && (first.nodeType === 3 || (first.matches && first.matches("svg.forge-glyph"))) ? first : null;
    const markup = current === "new" ? svg(id) : "";
    if (markup) {
      if (el.dataset.glyph === id && face && face.nodeType !== 3) return el;
      el.dataset.glyph = id;
    } else {
      delete el.dataset.glyph;
    }
    const word = markup ? "" : (current === "classic" && CLASSIC[id]) || fallback;
    // swapped in place only when the icon leads and more follows it; anything
    // else held here (a broken picture, an old icon) is cleared away
    if (!face || el.childNodes.length === 1) {
      if (markup) el.innerHTML = markup;
      else el.textContent = word;
      return el;
    }
    let node;
    if (markup) {
      const t = document.createElement("template");
      t.innerHTML = markup;
      node = t.content.firstChild;
    } else {
      node = document.createTextNode(word);
    }
    el.replaceChild(node, face);
    return el;
  }

  // An element that stops showing an app's icon (a folder's grid, album art)
  // drops its mark, so a style switch leaves it be.
  function forget(el) {
    for (const k of ["glyph", "icon", "iconText"]) delete el.dataset[k];
    return el;
  }

  // Anything but "classic" is the new style. True when the style changed.
  function setStyle(name, root) {
    const next = name === "classic" ? "classic" : "new";
    if (next === current) return false;
    current = next;
    (root || document).querySelectorAll("[data-icon]").forEach((el) => paint(el, el.dataset.icon, el.dataset.iconText));
    return true;
  }

  window.ForgeIcons = {
    svg,
    paint,
    forget,
    setStyle,
    style: () => current,
    styles: STYLES.slice(),
    classic: (id) => CLASSIC[id] || "",
    has: (id) => Object.prototype.hasOwnProperty.call(GLYPHS, id),
    ids: () => Object.keys(GLYPHS),
    classicIds: () => Object.keys(CLASSIC),
  };
})();
