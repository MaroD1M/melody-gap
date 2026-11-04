//! 运行目录解析。
//!
//! 便携版约定：配置、日志、待补清单、WebView2 数据都写在 exe 同目录，
//! 不在用户目录或系统目录产生额外文件。

use std::env;
use std::path::PathBuf;

use melodygap_core::constants::{CONFIG_FILE_NAME, MISSING_FILE_NAME};

pub fn app_dir() -> PathBuf {
    if let Ok(value) = env::var("MELODYGAP_APP_DIR") {
        if !value.trim().is_empty() {
            return PathBuf::from(value);
        }
    }
    env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(|parent| parent.to_path_buf()))
        .or_else(|| env::current_dir().ok())
        .unwrap_or_else(|| PathBuf::from("."))
}

pub fn config_path() -> PathBuf {
    app_dir().join(CONFIG_FILE_NAME)
}

pub fn missing_path() -> PathBuf {
    app_dir().join(MISSING_FILE_NAME)
}

pub fn webview_data_dir() -> PathBuf {
    app_dir().join("webview2-data")
}

/// 必须在 Tauri/WebView2 初始化前调用。
pub fn configure_webview2_data_dir() {
    let dir = webview_data_dir();
    let _ = std::fs::create_dir_all(&dir);
    env::set_var("WEBVIEW2_USER_DATA_FOLDER", dir.as_os_str());
}
