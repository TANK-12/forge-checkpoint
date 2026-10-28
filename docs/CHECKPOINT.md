# Forge event checkpoint — 28 October 2026

This preview saves the 0.2.0 candidate separately from daily development.
The bundled application code is the existing tested candidate. Source
packaging, documentation, install helpers, ignore rules and tests were adjusted
for this checkpoint; the shipped application code was not changed.

## What was checked for this checkpoint

- Linux: archive installed in a scratch home, welcome completed in headless
  Chrome, all 18 apps started, smoke **108 passed, 0 failed**. All 13 Windows
  apps and 17 of 18 Linux apps passed the visual/content probes. Linux Files
  sees the checking computer's mounted drives, so its content probe reported
  local drive names. That is a runtime display, not bundled user data; its
  pictures and raw logs are deliberately not published.
- Windows: the saved zip was unpacked into a fresh Wine prefix; welcome and
  all 13 apps checked in headless Chrome, smoke **83 passed, 0 failed**.
  Generated starter art passed on both platforms. Neither run wrote files
  into the program folder after installation.
- Mac: new Apple silicon and Intel archives built on Linux with the trusted
  release scrubber, private-value scanner and dependency licence checks.
  Archive paths, application layout, executable launcher, architecture of
  bundled Mach-O files, and minimum OS versions were checked independently.
  Both contain 14 apps; Apple silicon requires macOS 11+, Intel macOS 12+.
  Mac app payload files match the source snapshot apart from source-only
  release registry/export metadata. Shared Python package versions match
  the Windows candidate; the six Mac-specific PyObjC packages are 12.2.2.
  All 51 Apple silicon native slices carry signature commands, and the five
  CPython native files are byte-identical to the pinned upstream runtime.
  This is a static check, not native cryptographic signature verification.
- Public source: tested in its own Python 3.14 environment: **187 passed,
  3 skipped**; black and ruff clean, pyright 0 errors. The Mac install
  helper is exercised on Linux with small fixture archives and stand-ins for
  Mac commands, including paths with spaces, both CPU selections, bad or missing hashes,
  incomplete archives, wrong CPU and preserving an existing destination.
  This checks the script's logic, not macOS itself.
- The final source tree and complete newly created Git history are checked
  with the trusted local privacy checker before publication. The pushed
  history is fetched into a fresh local clone and checked before changing
  repository visibility to public. Archive source files use the same checker;
  third-party runtime/packages are scanned for secret patterns and known
  private values, preserving their authors' licence notices.

## Native hosted installation and smoke — checked at 16:12

[Run 40654815268](https://github.com/TANK-12/forge-checkpoint/actions/runs/40654815268) downloaded the fixed release assets, verified SHA256SUMS,
installed the full Mac and Windows archives with the supplied helpers, then
checked the installed app servers without opening a desktop window:

- Apple silicon Mac: **88 passed, 0 failed**, 14 apps.
- Intel Mac: **88 passed, 0 failed**, 14 apps.
- Windows: **83 passed, 0 failed**, 13 apps.
- Linux: **108 passed, 0 failed**, 18 apps (archive directly).

Helper fixture tests also passed on these native systems, including actual
Windows PowerShell, both destination forms, and the Mac platform tools.
An earlier Windows fixture run inherited PowerShell 7 module paths through
Python; the test child now clears PSModulePath as Microsoft's documentation
requires. That changed the test harness, not the install helper or app code.
The original dated package tag stays fixed. The updated source, including
this evidence and the test-environment fix, is tagged
`checkpoint-2026-10-28-tested` and is the attached source archive.

## What remains unverified

Interactive Mac/Windows desktop windows, Gatekeeper/quarantine, SmartScreen,
Defender policy, native dialogs, sound and GPU behavior still need a person
to check them. Native hosted backend checks do not establish those things.
The first installed-copy workflow failed in the Windows test environment;
the linked second run passed on every system after fixing that environment.

The separate build-from-source GitHub workflow has not run. Future builds
resolve transitive wheel dependencies, so they are not promised to be
byte-for-byte identical; the archived downloads and hashes are fixed.

The packages are unsigned; macOS notarisation and Windows signing are still
future work. No setup EXE is provided. The licence remains an explicit
all-rights-reserved placeholder until the owner chooses one.

## What was left out

Private apps, logins, API credentials,
owner settings, browser profiles, personal conversations and media, model
weights, virtual environments, outputs and development history do not ship.
The source repository has newly created history, not the daily repository's
history. Binary downloads include their own clean Python runtime/packages.

Hyprland/end4, systemd, Linux device and power control, mounts, desktop
widgets and daily launchers are not Mac/Windows features. Files, Convert,
Loops and Typeset are omitted on Mac/Windows; Terminal is omitted on Windows.
AI features need Jan and separately downloaded models. Research apps may
fetch public information only when requested. No heavy AI evaluation was run.

## First real-Mac check

1. Download the correct archive plus SHA256SUMS and install as in README.
2. Try both Archive Utility extraction and the optional helper. Open the app
   through the normal macOS security prompt, finish welcome,
   and open Arcade, Emberfield, Drift Peaks, Exo Lab, PrintForge and Settings.
3. Change the theme, close and reopen; check the saved look/data are kept.
4. Run `Forge.app/Contents/MacOS/Forge --smoke --report smoke.json` and keep
   that report. Do not publish a report containing your own paths unchecked.
5. If the native window fails, try `--window browser` and report the log.
