use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Wry};

use crate::events;
use crate::state::AppState;

const MENU_SHOW: &str = "show";
const MENU_MISSING: &str = "missing";
const MENU_MONITOR: &str = "monitor";
const MENU_QUIT: &str = "quit";

pub struct TrayState {
    missing_item: MenuItem<Wry>,
    monitor_item: MenuItem<Wry>,
}

pub fn setup(app: &AppHandle, state: &AppState) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, MENU_SHOW, "显示主界面", true, None::<&str>)?;
    let missing = MenuItem::with_id(app, MENU_MISSING, "待补清单", true, None::<&str>)?;
    let monitor = MenuItem::with_id(app, MENU_MONITOR, "停止监控", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, MENU_QUIT, "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &missing, &monitor, &separator, &quit])?;

    let icon = Image::from_bytes(include_bytes!("../icons/icon.png"))?;
    TrayIconBuilder::with_id("main")
        .icon(icon)
        .tooltip("MelodyGap 曲库补漏")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            MENU_SHOW => show_main(app),
            MENU_MISSING => {
                show_main(app);
                let _ = app.emit_to("main", "navigate", "missing");
            }
            MENU_MONITOR => {
                toggle_monitoring(app);
            }
            MENU_QUIT => {
                if let Some(state) = app.try_state::<AppState>() {
                    state
                        .quitting
                        .store(true, std::sync::atomic::Ordering::SeqCst);
                }
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main(tray.app_handle());
            }
        })
        .build(app)?;

    app.manage(TrayState {
        missing_item: missing,
        monitor_item: monitor,
    });
    refresh(app, state);
    Ok(())
}

pub fn refresh(app: &AppHandle, state: &AppState) {
    let Some(tray) = app.try_state::<TrayState>() else {
        return;
    };
    let _ = tray
        .missing_item
        .set_text(format!("待补清单（{} 首）", state.missing.count_pending()));
    let _ = tray.monitor_item.set_text(if state.monitor.is_running() {
        "停止监控"
    } else {
        "开始监控"
    });
}

pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub fn toggle_monitoring(app: &AppHandle) {
    let Some(state) = app.try_state::<AppState>() else {
        return;
    };
    let state = state.inner().clone();
    if state.monitor.is_running() {
        state.monitor.stop();
    } else {
        state.monitor.start();
    }
    events::broadcast(app, &state);
}
