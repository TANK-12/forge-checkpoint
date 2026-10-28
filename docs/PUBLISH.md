# Publishing this checkpoint

The checkpoint has a fresh Git history. Publish this source repository;
never push the daily development repository or a linked build worktree.
The original package tag is `checkpoint-2026-10-28`; the source follow-up
with native test evidence is `checkpoint-2026-10-28-tested`. Downloads go in a GitHub prerelease
under that tag rather than in Git, accompanied by SHA256SUMS and the two
optional install helpers. Keep local build reports and raw checking logs
private: they may describe the builder's machine and its mounted files.

The owner authorised a public repository after tree and pushed-history
privacy checks. The sequence below records that process; do not rerun repo
creation when the repository already exists.

```sh
# Run inside this clean source checkout, after tests and local history scan.
gh auth status
gh repo create TANK-12/forge-checkpoint --private --source . --remote origin
git push origin main checkpoint-2026-10-28
# Fetch a new copy and scan every reachable commit and commit metadata.
# If any finding is doubtful, keep the repository private until resolved.
gh repo edit TANK-12/forge-checkpoint --visibility public --accept-visibility-change-consequences
# Attach only approved archives, SHA256SUMS, helpers and release notes.
gh release create checkpoint-2026-10-28 --repo TANK-12/forge-checkpoint \
  --verify-tag --prerelease --title 'Forge checkpoint — 28 October 2026' \
  --notes-file docs/RELEASE-NOTES.txt \
  /path/to/approved/downloads/forge-0.2.0-macos-arm64.tar.gz \
  /path/to/approved/downloads/forge-0.2.0-macos-x64.tar.gz \
  /path/to/approved/downloads/forge-0.2.0-windows-x64.zip \
  /path/to/approved/downloads/forge-0.2.0-linux-x64.tar.gz \
  /path/to/approved/downloads/SHA256SUMS \
  /path/to/approved/downloads/install-macos.sh \
  /path/to/approved/downloads/install-windows.ps1
```

The complete local checkpoint includes private evidence beside this source
tree; that enclosing directory is not a publishable repository. Before any
future push, repeat the tree/history checks and choose a licence before
calling this an open-source release. No GitHub Action publishes automatically;
the included workflow only builds artifacts and runs smoke checks when started
manually. Its first native Mac/Windows run is the next useful verification.
