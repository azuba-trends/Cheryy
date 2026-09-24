// CHERYY Tauri shell.
//
// The Tauri shell is intentionally thin:
//   * No filesystem access from the webview.
//   * No arbitrary command execution.
//   * The webview talks only to a local FastAPI backend bundled as a sidecar.
//
// All real work happens in the Python backend (cheryy.api:app).

#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, State};

struct BackendProcess(Mutex<Option<Child>>);

fn main() {
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            let backend_path = app
                .path_resolver()
                .resolve_resource("cheryy-server.exe")
                .expect("backend binary must be bundled");
            if let Ok(port) = std::env::var("CHERYY_PORT") {
                // allow caller to override
                std::env::set_var("CHERYY_PORT", port);
            }
            match Command::new(&backend_path)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
            {
                Ok(child) => {
                    let state: State<BackendProcess> = app.state();
                    *state.0.lock().unwrap() = Some(child);
                }
                Err(e) => eprintln!("cheryy: failed to start backend: {e}"),
            }
            Ok(())
        })
        .on_window_event(|event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event.event() {
                // Stop backend when the window closes.
                let app = event.window().app_handle();
                if let Some(state) = app.try_state::<BackendProcess>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running CHERYY");
}
