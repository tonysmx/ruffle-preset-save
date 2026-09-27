# Ruffle + Binding of Isaac preset save + state snapshot prototype

This kit extends the same modified Ruffle build used for the preset `so.sol` save.
It adds a first-generation save-state system based on deterministic replay instead of
serializing the entire Ruffle GC heap.

## What the state file stores

- saved emulation frame
- initial AVM RNG seed
- every Ruffle input event recorded up to that point

On import, the webpage reloads a fresh Ruffle VM, restores the RNG seed, replays the
recorded input events frame-by-frame, then resumes play.

This is intended to reproduce game state such as Isaac's health and enemy positions when
the SWF behaves deterministically. It is **not** a byte-for-byte heap snapshot, so external
network activity, wall-clock-dependent behavior, or other nondeterminism could make a state
differ between runs.

## Web UI

The supplied `site/index.html` only loads the Binding of Isaac SWF. A small down-arrow in
the top-right opens:

- Export State
- Import State

The exported file uses the `.rstate` extension and contains JSON data.

## Build

The GitHub Actions workflow is pinned to the same Ruffle commit used by the existing
preset-save self-hosted build (`74ade97342205ac55d264f2ceb1e642573a21d48`).

The workflow combines:

1. the existing `web/src/storage.rs` preset-save modification,
2. the supplied `so.sol`, and
3. the new save-state patch.

Run **Actions → Build Ruffle with Isaac preset save + save states** with `workflow_dispatch`.
The resulting artifact is `ruffle-isaac-savestate-site.zip`.

## Important testing note

The Ruffle source cannot be compiled in this environment, so the patch is prepared for the
pinned GitHub Actions build and should be treated as a prototype until the Actions log and
an actual Binding of Isaac run confirm behavior.
