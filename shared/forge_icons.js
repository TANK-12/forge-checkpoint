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
