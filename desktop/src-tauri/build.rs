// CHERYY — Tauri build script.
//
// This file is the canonical Tauri 1.x build helper. Its only job is to call
// `tauri_build::build()`, which:
//   * generates the bundled resource manifest,
//   * parses `tauri.conf.json` from the package directory,
//   * emits `OUT_DIR` so `tauri::generate_context!()` can expand in `main.rs`,
//   * wires the Windows icon / NSIS hooks for the `tauri build` step.
//
// Cargo discovers this file by convention (no manifest edit needed).
fn main() {
    tauri_build::build();
}
