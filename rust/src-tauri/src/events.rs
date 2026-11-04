use tauri::{AppHandle, Emitter};

use crate::state::{snapshot, AppState};
use crate::tray;

pub fn broadcast(app: &AppHandle, state: &AppState) {
    let snap = snapshot(state);
    let _ = app.emit("state-changed", snap);
    tray::refresh(app, state);
}
