mod commands;
mod events;
mod logging;
mod notifications;
mod paths;
mod platform;
mod state;
mod tray;

use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex, OnceLock};

use tauri::{
    LogicalSize, Manager, PhysicalPosition, PhysicalSize, WebviewWindowBuilder, WindowEvent,
};

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
                notifications: Arc::new(OnceLock::new()),
                last_notified: Arc::new(Mutex::new(std::collections::HashMap::new())),
                rechecking: Arc::new(std::sync::atomic::AtomicBool::new(false)),
                quitting: Arc::new(std::sync::atomic::AtomicBool::new(false)),
            };

            app.manage(state.clone());

            let notifications = NotificationManager::new(app.handle().clone());
            let _ = state.notifications.set(notifications);

            create_main_window(app)?;

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

const MIN_WINDOW_WIDTH: f64 = 840.0;
const MIN_WINDOW_HEIGHT: f64 = 540.0;
const WINDOW_MARGIN: f64 = 16.0;

fn create_main_window(app: &mut tauri::App) -> tauri::Result<()> {
    let window_config = app
        .config()
        .app
        .windows
        .iter()
        .find(|config| config.label == "main")
        .expect("tauri.conf.json 缺少 main 窗口配置");
    let window = WebviewWindowBuilder::from_config(app.handle(), window_config)?.build()?;
    let _ = window.set_title(&format!(
        "MelodyGap 曲库补漏 v{}",
        env!("CARGO_PKG_VERSION")
    ));
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct WindowGeometry {
    width: f64,
    height: f64,
    x: i32,
    y: i32,
    logical: bool,
}

#[derive(Clone, Copy, Debug)]
struct ResolvedWindowGeometry {
    size: PhysicalSize<u32>,
    position: PhysicalPosition<i32>,
    min_size: LogicalSize<f64>,
}

fn restore_window(app: &tauri::AppHandle, state: &AppState) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let settings = {
        let config = state.config.lock().expect("config lock");
        config.get_app_settings()
    };
    let geometry = parse_geometry(&settings.window_geometry);
    let monitor = geometry
        .as_ref()
        .and_then(|saved| {
            app.monitor_from_point(saved.x as f64, saved.y as f64)
                .ok()
                .flatten()
        })
        .or_else(|| window.current_monitor().ok().flatten())
        .or_else(|| app.primary_monitor().ok().flatten());

    if let Some(monitor) = monitor {
        let work_area = monitor.work_area();
        let fallback_size = window
            .inner_size()
            .unwrap_or_else(|_| PhysicalSize::new(1120, 800));
        let resolved = resolve_window_geometry(
            geometry.as_ref(),
            fallback_size,
            work_area.position,
            work_area.size,
            monitor.scale_factor(),
        );
        let _ = window.set_size(resolved.size);
        let _ = window.set_position(resolved.position);
        let _ = window.set_min_size(Some(resolved.min_size));
    } else {
        let _ = window.center();
    }

    if settings.window_zoomed {
        let _ = window.maximize();
    }
    let _ = window.show();
    let _ = window.set_focus();
}

fn resolve_window_geometry(
    saved: Option<&WindowGeometry>,
    fallback_size: PhysicalSize<u32>,
    work_position: PhysicalPosition<i32>,
    work_size: PhysicalSize<u32>,
    scale_factor: f64,
) -> ResolvedWindowGeometry {
    let scale = if scale_factor.is_finite() && scale_factor > 0.0 {
        scale_factor
    } else {
        1.0
    };
    let available_width = (work_size.width as f64 / scale - WINDOW_MARGIN * 2.0).max(320.0);
    let available_height = (work_size.height as f64 / scale - WINDOW_MARGIN * 2.0).max(240.0);
    let (desired_width, desired_height) = match saved {
        Some(saved) if saved.logical => (saved.width, saved.height),
        Some(saved) => (saved.width / scale, saved.height / scale),
        None => (
            fallback_size.width as f64 / scale,
            fallback_size.height as f64 / scale,
        ),
    };
    let min_width = MIN_WINDOW_WIDTH.min(available_width);
    let min_height = MIN_WINDOW_HEIGHT.min(available_height);
    let width = desired_width.clamp(min_width, available_width);
    let height = desired_height.clamp(min_height, available_height);
    let physical_size = PhysicalSize::new(
        (width * scale).round().max(1.0) as u32,
        (height * scale).round().max(1.0) as u32,
    );
    let position = match saved {
        Some(saved) => PhysicalPosition::new(
            clamp_axis(
                saved.x,
                work_position.x,
                work_size.width,
                physical_size.width,
            ),
            clamp_axis(
                saved.y,
                work_position.y,
                work_size.height,
                physical_size.height,
            ),
        ),
        None => PhysicalPosition::new(
            work_position.x
                + ((work_size.width as i64 - physical_size.width as i64) / 2).max(0) as i32,
            work_position.y
                + ((work_size.height as i64 - physical_size.height as i64) / 2).max(0) as i32,
        ),
    };

    ResolvedWindowGeometry {
        size: physical_size,
        position,
        min_size: LogicalSize::new(min_width, min_height),
    }
}

fn clamp_axis(value: i32, start: i32, area: u32, size: u32) -> i32 {
    let start = start as i64;
    let area = area as i64;
    let size = size as i64;
    if size >= area {
        start as i32
    } else {
        (value as i64).clamp(start, start + area - size) as i32
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
    let scale = window.scale_factor().unwrap_or(1.0);
    let geometry = format_logical_geometry(size, position, scale);
    let mut config = state.config.lock().expect("config lock");
    if let Err(error) = config.set_window_geometry(&geometry, zoomed) {
        tracing::error!(%error, "保存窗口位置失败");
    }
}

fn format_logical_geometry(
    size: PhysicalSize<u32>,
    position: PhysicalPosition<i32>,
    scale: f64,
) -> String {
    let scale = if scale.is_finite() && scale > 0.0 {
        scale
    } else {
        1.0
    };
    let logical = size.to_logical::<f64>(scale);
    format!(
        "logical:{}x{}{:+}{:+}",
        logical.width.round().max(1.0) as u32,
        logical.height.round().max(1.0) as u32,
        position.x,
        position.y
    )
}

fn parse_geometry(value: &str) -> Option<WindowGeometry> {
    let trimmed = value.trim();
    let (logical, value) = match trimmed.strip_prefix("logical:") {
        Some(rest) => (true, rest),
        None => (false, trimmed),
    };
    let (width, rest) = value.split_once('x')?;
    let width = width.parse::<f64>().ok()?;
    if !width.is_finite() || width <= 0.0 {
        return None;
    }
    let index = rest.find(['+', '-'])?;
    let height = rest[..index].parse::<f64>().ok()?;
    if !height.is_finite() || height <= 0.0 {
        return None;
    }
    let mut rest = &rest[index..];
    let x = take_coordinate(&mut rest)?;
    let y = take_coordinate(&mut rest)?;
    if !rest.is_empty() {
        return None;
    }
    Some(WindowGeometry {
        width,
        height,
        x,
        y,
        logical,
    })
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
    use super::{format_logical_geometry, parse_geometry, resolve_window_geometry, WindowGeometry};
    use tauri::{PhysicalPosition, PhysicalSize};

    fn geometry(width: f64, height: f64, x: i32, y: i32, logical: bool) -> WindowGeometry {
        WindowGeometry {
            width,
            height,
            x,
            y,
            logical,
        }
    }

    #[test]
    fn parses_legacy_and_logical_window_geometry() {
        assert_eq!(
            parse_geometry("1080x760+100+100"),
            Some(geometry(1080.0, 760.0, 100, 100, false))
        );
        assert_eq!(
            parse_geometry("1080x760-100-100"),
            Some(geometry(1080.0, 760.0, -100, -100, false))
        );
        assert_eq!(
            parse_geometry("logical:1120x800+100-100"),
            Some(geometry(1120.0, 800.0, 100, -100, true))
        );
        assert_eq!(
            parse_geometry("1080x760+-100+-100"),
            Some(geometry(1080.0, 760.0, -100, -100, false))
        );
        assert_eq!(
            parse_geometry("1080x760+0-0"),
            Some(geometry(1080.0, 760.0, 0, 0, false))
        );
        assert_eq!(parse_geometry("1080x760"), None);
        assert_eq!(parse_geometry("logical:0x800+0+0"), None);
        assert_eq!(parse_geometry("bad"), None);
    }

    #[test]
    fn formats_logical_geometry_with_signed_position() {
        assert_eq!(
            format_logical_geometry(
                PhysicalSize::new(1400, 1000),
                PhysicalPosition::new(-120, 80),
                1.25
            ),
            "logical:1120x800-120+80"
        );
    }

    #[test]
    fn restores_logical_size_independently_of_dpi() {
        let resolved = resolve_window_geometry(
            Some(&geometry(1120.0, 800.0, 100, 100, true)),
            PhysicalSize::new(1400, 1000),
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(2560, 1400),
            1.25,
        );
        assert_eq!(resolved.size, PhysicalSize::new(1400, 1000));
        assert_eq!(resolved.position, PhysicalPosition::new(100, 100));
    }

    #[test]
    fn converts_legacy_physical_geometry_to_logical_size() {
        let resolved = resolve_window_geometry(
            Some(&geometry(1400.0, 1000.0, 100, 100, false)),
            PhysicalSize::new(1120, 800),
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(2560, 1400),
            1.25,
        );
        assert_eq!(resolved.size, PhysicalSize::new(1400, 1000));
    }

    #[test]
    fn clamps_to_logical_work_area_on_high_dpi() {
        let resolved = resolve_window_geometry(
            Some(&geometry(3000.0, 2000.0, 0, 0, true)),
            PhysicalSize::new(1120, 800),
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(2880, 1620),
            1.5,
        );
        assert_eq!(resolved.size, PhysicalSize::new(2832, 1572));
        assert_eq!(resolved.position, PhysicalPosition::new(0, 0));
    }

    #[test]
    fn clamps_oversized_and_offscreen_windows() {
        let resolved = resolve_window_geometry(
            Some(&geometry(2400.0, 2000.0, 1800, 900, true)),
            PhysicalSize::new(1120, 800),
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(1920, 1040),
            1.0,
        );
        assert_eq!(resolved.size, PhysicalSize::new(1888, 1008));
        assert_eq!(resolved.position, PhysicalPosition::new(32, 32));
    }

    #[test]
    fn centers_first_run_window_inside_work_area() {
        let resolved = resolve_window_geometry(
            None,
            PhysicalSize::new(1400, 1000),
            PhysicalPosition::new(0, 0),
            PhysicalSize::new(1920, 1040),
            1.25,
        );
        assert_eq!(resolved.size, PhysicalSize::new(1400, 1000));
        assert_eq!(resolved.position, PhysicalPosition::new(260, 20));
    }
}
