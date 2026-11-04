use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Local};
use serde::Serialize;

use melodygap_core::config::ConfigManager;
use melodygap_core::constants::{APP_DISPLAY_NAME, APP_VERSION};
use melodygap_core::missing_repository::MissingRepository;
use melodygap_core::models::{MissingSong, PlayRecord, SongInfo};
use melodygap_core::monitor::MusicMonitor;

use crate::notifications::NotificationManager;
use crate::platform::HybridDetector;

#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Mutex<ConfigManager>>,
    pub monitor: Arc<MusicMonitor>,
    pub missing: Arc<MissingRepository>,
    pub detector: Arc<HybridDetector>,
    pub notifications: Arc<NotificationManager>,
    pub last_notified: Arc<Mutex<HashMap<String, DateTime<Local>>>>,
    pub rechecking: Arc<AtomicBool>,
    pub quitting: Arc<AtomicBool>,
}

#[derive(Clone, Debug, Serialize)]
pub struct SubsonicView {
    pub server_url: String,
    pub username: String,
    pub verify_ssl: bool,
    pub password_set: bool,
    pub configured: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct SettingsView {
    pub reminder_mode: String,
    pub reminder_cooldown_minutes: i64,
    pub window_geometry: String,
    pub window_zoomed: bool,
    pub last_tab: i64,
}

#[derive(Clone, Debug, Serialize)]
pub struct Snapshot {
    pub app_name: String,
    pub app_version: String,
    pub running: bool,
    pub current_songs: BTreeMap<String, SongInfo>,
    pub current_records: BTreeMap<String, PlayRecord>,
    pub current_sources: BTreeMap<String, String>,
    pub history: Vec<PlayRecord>,
    pub missing: Vec<MissingSong>,
    pub settings: SettingsView,
    pub subsonic: SubsonicView,
    pub query_ok: bool,
    pub last_query_error: Option<String>,
    pub missing_count: usize,
    pub smtc_available: bool,
    pub smtc_error: Option<String>,
}

pub fn snapshot(state: &AppState) -> Snapshot {
    let (settings, subsonic, configured) = {
        let config = state.config.lock().expect("config lock");
        let subsonic = config.get_subsonic_config();
        (
            config.get_app_settings(),
            subsonic,
            config.is_subsonic_configured(),
        )
    };

    Snapshot {
        app_name: APP_DISPLAY_NAME.to_string(),
        app_version: APP_VERSION.to_string(),
        running: state.monitor.is_running(),
        current_songs: state.monitor.current_songs(),
        current_records: state.monitor.current_records(),
        current_sources: state.monitor.current_sources(),
        history: state.monitor.play_history(),
        missing: state.missing.snapshot(),
        settings: SettingsView {
            reminder_mode: settings.reminder_mode,
            reminder_cooldown_minutes: settings.reminder_cooldown_minutes,
            window_geometry: settings.window_geometry,
            window_zoomed: settings.window_zoomed,
            last_tab: settings.last_tab,
        },
        subsonic: SubsonicView {
            server_url: subsonic.server_url,
            username: subsonic.username,
            verify_ssl: subsonic.verify_ssl,
            password_set: !subsonic.password.is_empty(),
            configured,
        },
        query_ok: state.monitor.query_ok(),
        last_query_error: state.monitor.last_query_error(),
        missing_count: state.missing.count_pending(),
        smtc_available: state.detector.smtc_available(),
        smtc_error: state.detector.smtc_error(),
    }
}
