# Ruffle Preset Save Modifier

This modifies Ruffle's web SharedObject backend so the first SharedObject
whose storage key ends with `/so` receives the embedded `so.sol` save.

The modifier is intentionally applied to the web storage backend rather than
HTML/JavaScript localStorage. Ruffle's web backend normally decodes base64
from localStorage and returns the raw SOL bytes to the core.

## Target

SWF:
https://cdn.imageurlgenerator.com/uploads/8bc8b86f-095b-4862-b7d8-527989a6ecaa.swf

Embedded SharedObject:
so

Embedded SOL:
4,285 bytes

## Files

- `web/src/storage.rs` — patched Ruffle source file
- `preset-save.patch` — unified diff against current Ruffle `master`
- `so.sol` — original save file
- `.github/workflows/build-ruffle-preset.yml` — GitHub Actions build workflow

## Build locally

From a Ruffle source checkout, replace `web/src/storage.rs` with the supplied
version, or apply `preset-save.patch`.

Then follow Ruffle's current web build requirements and run:

    cd web
    npm install
    npm run build

The selfhosted package is produced under:

    web/packages/selfhosted/dist/

Ruffle's web README currently documents Rust + wasm32, Java, Node.js, and
wasm-bindgen 0.2.127 as required build components.

## Important behavior

The preset is consumed only once. After that, Ruffle reads and writes the
browser's normal localStorage backend.

This means the preset should load on first launch, while subsequent game
saves can persist normally.

If the game still starts with a new save after using this build, the next
thing to inspect is the SharedObject name used by the SWF; the patch currently
targets names ending in `/so` based on the uploaded save.
