mod commands;
mod events;
mod logging;
mod notifications;
mod paths;
mod platform;
mod state;
mod tray;

use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};

use tauri::{Manager, PhysicalPosition, PhysicalSize, WindowEvent};

use melodygap_core::config::ConfigManager;
use melodygap_core::missing_repository::MissingRepository;
use melodygap_core::monitor::MusicMonitor;

use notifications::NotificationManager;
use platform::hybrid::DetectorHandle;
use platform::HybridDetector;
use state::AppState;

pub fn smoke_test() -> i32 {
    paths::configure_webview2_data_dir();
    let dir = paths::webview_data_dir();
    match std::fs::create_dir_all(&dir) {
        Ok(()) => 0,
        Err(_) => 2,
    }
}

pub fn run() {
    paths::configure_webview2_data_dir();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            tray::show_main(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            commands::get_snapshot,
            commands::start_monitoring,
            commands::stop_monitoring,
            commands::save_last_tab,
            commands::save_settings,
            commands::test_connection,
            commands::recheck_current,
            commands::recheck_missing,
            commands::set_missing_status,
            commands::set_missing_status_many,
            commands::delete_missing,
            commands::delete_missing_many,
            commands::clear_history,
            commands::get_current_notification,
            commands::dismiss_notification,
            commands::export_missing,
            commands::export_history,
        ])
        .setup(|app| {
            let app_dir = paths::app_dir();
            logging::init(&app_dir);
            tracing::info!(dir = %app_dir.display(), "MelodyGap 启动");

            let config = Arc::new(Mutex::new(ConfigManager::new(paths::config_path())?));
            let missing = Arc::new(MissingRepository::new(paths::missing_path()));
            let detector = Arc::new(HybridDetector::new());
            let notifications = NotificationManager::new(app.handle().clone());
            let monitor = Arc::new(MusicMonitor::new(
                Arc::clone(&config),
                Box::new(DetectorHandle(Arc::clone(&detector))),
                None,
            ));

            let state = AppState {
                config,
                monitor,
                missing,
                detector,
                notifications,
                last_notified: Arc::new(Mutex::new(std::collections::HashMap::new())),
                rechecking: Arc::new(std::sync::atomic::AtomicBool::new(false)),
                quitting: Arc::new(std::sync::atomic::AtomicBool::new(false)),
            };
            app.manage(state.clone());
            commands::install_record_callback(app.handle(), &state);

            if let Err(error) = tray::setup(app.handle(), &state) {
                tracing::error!(%error, "创建托盘失败，将使用纯窗口模式");
            }

            restore_window(app.handle(), &state);
            install_close_handler(app.handle());
            state.monitor.start();
            events::broadcast(app.handle(), &state);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("构建 MelodyGap 失败");

    app.run(|app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            if let Some(state) = app_handle.try_state::<AppState>() {
                save_window_state(app_handle, &state);
                state.monitor.stop();
            }
            tracing::info!("MelodyGap 已退出");
        }
    });
}

fn restore_window(app: &tauri::AppHandle, state: &AppState) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let settings = {
        let config = state.config.lock().expect("config lock");
        config.get_app_settings()
    };
    if let Some((width, height, x, y)) = parse_geometry(&settings.window_geometry) {
        let _ = window.set_size(PhysicalSize::new(width.max(640), height.max(480)));
        let _ = window.set_position(PhysicalPosition::new(x, y));
    }
    if settings.window_zoomed {
        let _ = window.maximize();
    }
}

fn install_close_handler(app: &tauri::AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let app_handle = app.clone();
    window.on_window_event(move |event| {
        let WindowEvent::CloseRequested { api, .. } = event else {
            return;
        };
        let Some(state) = app_handle.try_state::<AppState>() else {
            return;
        };
        if state.quitting.load(Ordering::SeqCst) {
            return;
        }
        api.prevent_close();
        save_window_state(&app_handle, state.inner());
        if app_handle.tray_by_id("main").is_some() {
            if let Some(window) = app_handle.get_webview_window("main") {
                let _ = window.hide();
            }
        } else {
            state.quitting.store(true, Ordering::SeqCst);
            app_handle.exit(0);
        }
    });
}

pub fn save_window_state(app: &tauri::AppHandle, state: &AppState) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let Ok(size) = window.inner_size() else {
        return;
    };
    let Ok(position) = window.outer_position() else {
        return;
    };
    let zoomed = window.is_maximized().unwrap_or(false);
    let geometry = format!(
        "{}x{}+{}+{}",
        size.width, size.height, position.x, position.y
    );
    let mut config = state.config.lock().expect("config lock");
    if let Err(error) = config.set_window_geometry(&geometry, zoomed) {
        tracing::error!(%error, "保存窗口位置失败");
    }
}

fn parse_geometry(value: &str) -> Option<(u32, u32, i32, i32)> {
    let trimmed = value.trim();
    let (width, rest) = trimmed.split_once('x')?;
    let width = width.parse::<u32>().ok()?;
    let index = rest.find(['+', '-'])?;
    let height = rest[..index].parse::<u32>().ok()?;
    let mut rest = &rest[index..];
    let x = take_coordinate(&mut rest)?;
    let y = take_coordinate(&mut rest)?;
    if !rest.is_empty() {
        return None;
    }
    Some((width, height, x, y))
}

fn take_coordinate(value: &mut &str) -> Option<i32> {
    let bytes = value.as_bytes();
    let mut index = 0;
    let mut negative = false;
    while index < bytes.len() && (bytes[index] == b'+' || bytes[index] == b'-') {
        negative |= bytes[index] == b'-';
        index += 1;
    }
    let digits_start = index;
    while index < bytes.len() && bytes[index].is_ascii_digit() {
        index += 1;
    }
    if index == digits_start {
        return None;
    }
    let number = value[digits_start..index].parse::<i32>().ok()?;
    *value = &value[index..];
    Some(if negative { -number } else { number })
}

#[cfg(test)]
mod tests {
    use super::parse_geometry;

    #[test]
    fn parses_window_geometry() {
        assert_eq!(
            parse_geometry("1080x760+100+100"),
            Some((1080, 760, 100, 100))
        );
        assert_eq!(
            parse_geometry("1080x760-100-100"),
            Some((1080, 760, -100, -100))
        );
        assert_eq!(
            parse_geometry("1080x760+-100+-100"),
            Some((1080, 760, -100, -100))
        );
        assert_eq!(parse_geometry("1080x760+0-0"), Some((1080, 760, 0, 0)));
        assert_eq!(parse_geometry("1080x760"), None);
        assert_eq!(parse_geometry("bad"), None);
    }
}
