use std::collections::BTreeSet;
use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::Ordering;

use chrono::Local;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, State};

use melodygap_core::config::SubsonicConfig;
use melodygap_core::constants::{
    is_valid_missing_status, is_valid_reminder_mode, player_display_name, DEFAULT_REMINDER_MODE,
};
use melodygap_core::matcher::make_song_key;
use melodygap_core::models::{MissingSong, PlayRecord, SongInfo};
use melodygap_core::reminder::should_notify;
use melodygap_core::subsonic::{normalize_server_url, SubsonicClient};

use crate::events;
use crate::notifications::NotificationItem;
use crate::state::{snapshot, AppState, Snapshot};

#[derive(Clone, Debug, Serialize)]
pub struct ActionResponse {
    pub message: String,
    pub snapshot: Snapshot,
}

#[derive(Clone, Debug, Serialize)]
pub struct TestResponse {
    pub ok: bool,
    pub message: String,
    pub server_type: String,
    pub server_version: String,
    pub api_version: String,
}

#[derive(Clone, Debug, Deserialize)]
pub struct SettingsPayload {
    pub server_url: String,
    pub username: String,
    pub password: String,
    pub verify_ssl: bool,
    pub reminder_mode: String,
    pub reminder_cooldown_minutes: i64,
    pub last_tab: i64,
    #[serde(default)]
    pub clear_password: bool,
}

#[derive(Clone, Debug, Deserialize)]
pub struct ConnectionPayload {
    pub server_url: String,
    pub username: String,
    pub password: String,
    pub verify_ssl: bool,
}

fn validate_server_url(value: &str) -> Result<String, String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err("请填写服务器地址".to_string());
    }
    let lowered = trimmed.to_lowercase();
    if !lowered.starts_with("http://") && !lowered.starts_with("https://") {
        return Err("服务器地址必须以 http:// 或 https:// 开头".to_string());
    }
    let normalized = normalize_server_url(trimmed);
    if normalized.is_empty() {
        return Err("服务器地址无效".to_string());
    }
    Ok(normalized)
}

#[tauri::command]
pub fn get_snapshot(state: State<'_, AppState>) -> Snapshot {
    snapshot(&state)
}

#[tauri::command]
pub fn start_monitoring(app: AppHandle, state: State<'_, AppState>) -> Snapshot {
    state.monitor.start();
    events::broadcast(&app, &state);
    snapshot(&state)
}

#[tauri::command]
pub fn stop_monitoring(app: AppHandle, state: State<'_, AppState>) -> Snapshot {
    state.monitor.stop();
    events::broadcast(&app, &state);
    snapshot(&state)
}

#[tauri::command]
pub fn save_last_tab(app: AppHandle, state: State<'_, AppState>, tab: i64) -> Snapshot {
    {
        let mut config = state.config.lock().expect("config lock");
        if let Err(error) = config.set_last_tab(tab) {
            tracing::error!(%error, "保存页签失败");
        }
    }
    events::broadcast(&app, &state);
    snapshot(&state)
}

#[tauri::command]
pub fn save_settings(
    app: AppHandle,
    state: State<'_, AppState>,
    payload: SettingsPayload,
) -> Result<ActionResponse, String> {
    let reminder_mode = if is_valid_reminder_mode(&payload.reminder_mode) {
        payload.reminder_mode.clone()
    } else {
        DEFAULT_REMINDER_MODE.to_string()
    };
    let cooldown = payload.reminder_cooldown_minutes;
    if !(0..=1440).contains(&cooldown) {
        return Err("提醒冷却时间需在 0~1440 分钟之间".to_string());
    }
    let last_tab = payload.last_tab.max(0);
    let server_url = format!("{}/", validate_server_url(&payload.server_url)?);
    let username = payload.username.trim().to_string();
    if username.is_empty() {
        return Err("请填写用户名".to_string());
    }

    {
        let mut config = state.config.lock().expect("config lock");
        let existing = config.get_subsonic_config();
        let password = if payload.clear_password {
            String::new()
        } else if payload.password.is_empty() {
            existing.password
        } else {
            payload.password.clone()
        };
        if !payload.clear_password && password.trim().is_empty() {
            return Err("请填写密码".to_string());
        }
        config
            .update_subsonic_config(&SubsonicConfig {
                server_url,
                username,
                password,
                verify_ssl: payload.verify_ssl,
            })
            .map_err(|error| error.to_string())?;

        let mut settings = config.get_app_settings();
        settings.reminder_mode = reminder_mode;
        settings.reminder_cooldown_minutes = cooldown;
        settings.last_tab = last_tab;
        config
            .update_app_settings(&settings)
            .map_err(|error| error.to_string())?;
    }

    state.monitor.reload_config();
    events::broadcast(&app, &state);
    Ok(ActionResponse {
        message: "设置已保存，服务器配置已生效".to_string(),
        snapshot: snapshot(&state),
    })
}

#[tauri::command]
pub async fn test_connection(
    state: State<'_, AppState>,
    payload: ConnectionPayload,
) -> Result<TestResponse, String> {
    let server_url = validate_server_url(&payload.server_url)?;
    let username = payload.username.trim().to_string();
    if username.is_empty() {
        return Err("请填写用户名".to_string());
    }
    let existing = {
        let config = state.config.lock().expect("config lock");
        config.get_subsonic_config()
    };
    let password = if payload.password.is_empty() {
        existing.password
    } else {
        payload.password.clone()
    };
    if password.trim().is_empty() {
        return Err("请填写密码".to_string());
    }

    tauri::async_runtime::spawn_blocking(move || {
        let client =
            SubsonicClient::with_defaults(&server_url, &username, &password, payload.verify_ssl)
                .map_err(|error| error.to_string())?;
        match client.ping() {
            Ok(info) => Ok(TestResponse {
                ok: true,
                message: format!(
                    "连接成功：{} {}（API {}）",
                    if info.server_type.is_empty() {
                        "Subsonic"
                    } else {
                        info.server_type.as_str()
                    },
                    info.server_version,
                    info.api_version
                ),
                server_type: info.server_type,
                server_version: info.server_version,
                api_version: info.api_version,
            }),
            Err(error) => Ok(TestResponse {
                ok: false,
                message: format!("连接失败：{error}"),
                server_type: String::new(),
                server_version: String::new(),
                api_version: String::new(),
            }),
        }
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
pub async fn recheck_current(
    app: AppHandle,
    state: State<'_, AppState>,
    player: Option<String>,
) -> Result<ActionResponse, String> {
    let state = state.inner().clone();
    let task_state = state.clone();
    let rechecking = std::sync::Arc::clone(&state.rechecking);
    let result = tauri::async_runtime::spawn_blocking(move || {
        if rechecking.swap(true, Ordering::SeqCst) {
            return Err("已有核验任务正在进行，请稍候".to_string());
        }
        let state = task_state;
        let songs: Vec<SongInfo> = match player.as_deref() {
            Some(key) => state
                .monitor
                .current_songs()
                .get(key)
                .cloned()
                .into_iter()
                .collect(),
            None => state.monitor.current_songs().into_values().collect(),
        };
        let mut messages = Vec::new();
        for song in songs {
            let result = state.monitor.recheck_song(&song);
            let applied = state.monitor.update_current_result(
                &song.artist,
                &song.title,
                result,
                Some(&song.player),
            );
            if !applied {
                messages.push(format!("{}：歌曲已切换，结果未应用", song.title));
                continue;
            }
            match result {
                Some(true) => {
                    let _ = state.missing.resolve_song(&song.artist, &song.title);
                    messages.push(format!("{}：已在曲库", song.title));
                }
                Some(false) => {
                    if let Some(record) = state.monitor.current_records().get(&song.player) {
                        let _ = state.missing.ensure_missing(record);
                    }
                    messages.push(format!("{}：不在曲库", song.title));
                }
                None => {
                    let error = state
                        .monitor
                        .last_query_error()
                        .unwrap_or_else(|| "未知错误".to_string());
                    messages.push(format!("{}：查询失败（{error}）", song.title));
                }
            }
        }
        state.rechecking.store(false, Ordering::SeqCst);
        Ok::<String, String>(if messages.is_empty() {
            "没有可核验的当前歌曲".to_string()
        } else {
            messages.join("；")
        })
    })
    .await
    .map_err(|error| error.to_string())??;

    events::broadcast(&app, &state);
    Ok(ActionResponse {
        message: result,
        snapshot: snapshot(&state),
    })
}

#[tauri::command]
pub async fn recheck_missing(
    app: AppHandle,
    state: State<'_, AppState>,
    keys: Option<Vec<String>>,
    quiet: Option<bool>,
) -> Result<ActionResponse, String> {
    let state = state.inner().clone();
    let task_state = state.clone();
    let rechecking = std::sync::Arc::clone(&state.rechecking);
    let result = tauri::async_runtime::spawn_blocking(move || {
        if rechecking.swap(true, Ordering::SeqCst) {
            return Err("已有核验任务正在进行，请稍候".to_string());
        }
        let state = task_state;
        let show_notification = !quiet.unwrap_or(false);
        let selected: Option<BTreeSet<String>> =
            keys.map(|keys| keys.into_iter().collect::<BTreeSet<_>>());
        let entries: Vec<MissingSong> = state
            .missing
            .snapshot()
            .into_iter()
            .filter(|entry| match &selected {
                Some(selected) => selected.contains(&entry.key),
                None => entry.status == "pending",
            })
            .collect();
        if entries.is_empty() {
            state.rechecking.store(false, Ordering::SeqCst);
            return Ok::<String, String>("没有可核验的待补歌曲".to_string());
        }

        let mut in_library = 0usize;
        let mut missing = 0usize;
        let mut unknown = 0usize;
        for entry in entries {
            let song = SongInfo::new(&entry.title, &entry.artist, &entry.player);
            let result = state.monitor.recheck_song(&song);
            let _ = state.monitor.update_current_result(
                &entry.artist,
                &entry.title,
                result,
                Some(&entry.player),
            );
            match result {
                Some(true) => {
                    in_library += 1;
                    let _ = state.missing.remove_key(&entry.key);
                }
                Some(false) => missing += 1,
                None => unknown += 1,
            }
            if show_notification {
                if let Some(notifications) = state.notifications() {
                    notifications.push(NotificationItem {
                        id: 0,
                        title: entry.title.clone(),
                        artist: entry.artist.clone(),
                        status: result,
                        player: entry.player.clone(),
                        player_name: player_display_name(&entry.player).to_string(),
                        is_new_missing: false,
                        copy_text: if result == Some(false) {
                            format!("{} - {}", entry.title, entry.artist)
                        } else {
                            String::new()
                        },
                    });
                }
            }
        }
        state.rechecking.store(false, Ordering::SeqCst);
        Ok::<String, String>(format!(
            "核验完成：已入库 {in_library} 首，仍缺失 {missing} 首，查询失败 {unknown} 首"
        ))
    })
    .await
    .map_err(|error| error.to_string())??;

    events::broadcast(&app, &state);
    Ok(ActionResponse {
        message: result,
        snapshot: snapshot(&state),
    })
}

#[tauri::command]
pub fn set_missing_status(
    app: AppHandle,
    state: State<'_, AppState>,
    key: String,
    status: String,
) -> Result<ActionResponse, String> {
    if !is_valid_missing_status(&status) {
        return Err(format!("未知的待补状态: {status}"));
    }
    let updated = state
        .missing
        .set_status(&key, &status)
        .map_err(|error| error.to_string())?;
    let message = if updated {
        "状态已更新".to_string()
    } else {
        "歌曲已不在待补清单".to_string()
    };
    events::broadcast(&app, &state);
    Ok(ActionResponse {
        message,
        snapshot: snapshot(&state),
    })
}

#[tauri::command]
pub fn set_missing_status_many(
    app: AppHandle,
    state: State<'_, AppState>,
    keys: Vec<String>,
    status: String,
) -> Result<ActionResponse, String> {
    if !is_valid_missing_status(&status) {
        return Err(format!("未知的待补状态: {status}"));
    }
    let updated = state
        .missing
        .set_status_many(&keys, &status)
        .map_err(|error| error.to_string())?;
    let message = if updated == 0 {
        "选中的歌曲状态没有变化".to_string()
    } else {
        format!("已更新 {updated} 首歌曲状态")
    };
    events::broadcast(&app, &state);
    Ok(ActionResponse {
        message,
        snapshot: snapshot(&state),
    })
}

#[tauri::command]
pub fn delete_missing_many(
    app: AppHandle,
    state: State<'_, AppState>,
    keys: Vec<String>,
) -> Result<ActionResponse, String> {
    let removed = state
        .missing
        .remove_many(&keys)
        .map_err(|error| error.to_string())?;
    let message = if removed == 0 {
        "歌曲已不在待补清单".to_string()
    } else {
        format!("已从待补清单删除 {removed} 首歌曲")
    };
    events::broadcast(&app, &state);
    Ok(ActionResponse {
        message,
        snapshot: snapshot(&state),
    })
}

#[tauri::command]
pub fn delete_missing(
    app: AppHandle,
    state: State<'_, AppState>,
    key: String,
) -> Result<ActionResponse, String> {
    let removed = state
        .missing
        .remove_key(&key)
        .map_err(|error| error.to_string())?;
    let message = if removed {
        "已从待补清单删除".to_string()
    } else {
        "歌曲已不在待补清单".to_string()
    };
    events::broadcast(&app, &state);
    Ok(ActionResponse {
        message,
        snapshot: snapshot(&state),
    })
}

#[tauri::command]
pub fn clear_history(app: AppHandle, state: State<'_, AppState>) -> Snapshot {
    state.monitor.clear_history();
    events::broadcast(&app, &state);
    snapshot(&state)
}

#[tauri::command]
pub fn get_current_notification(state: State<'_, AppState>) -> Option<NotificationItem> {
    state.notifications().and_then(|manager| manager.current())
}

#[tauri::command]
pub fn dismiss_notification(state: State<'_, AppState>, id: Option<u64>) {
    if let Some(notifications) = state.notifications() {
        match id {
            Some(id) => notifications.dismiss_if(id),
            None => notifications.dismiss(),
        }
    }
}

fn create_csv_writer(path: &str) -> Result<csv::Writer<File>, String> {
    let mut file = File::create(path).map_err(|error| format!("无法写入文件：{error}"))?;
    file.write_all(b"\xEF\xBB\xBF")
        .map_err(|error| format!("无法写入文件：{error}"))?;
    Ok(csv::WriterBuilder::new()
        .terminator(csv::Terminator::CRLF)
        .from_writer(file))
}

#[tauri::command]
pub fn export_missing(
    state: State<'_, AppState>,
    path: String,
    keys: Vec<String>,
) -> Result<String, String> {
    let all = state.missing.snapshot();
    let entries: Vec<MissingSong> = if keys.is_empty() {
        all
    } else {
        let mut by_key: std::collections::HashMap<String, MissingSong> = all
            .into_iter()
            .map(|entry| (entry.key.clone(), entry))
            .collect();
        keys.into_iter()
            .filter_map(|key| by_key.remove(&key))
            .collect()
    };
    if entries.is_empty() {
        return Err("没有可导出的歌曲".to_string());
    }

    if Path::new(&path)
        .extension()
        .is_some_and(|extension| extension.eq_ignore_ascii_case("txt"))
    {
        let text = entries
            .iter()
            .map(MissingSong::copy_text)
            .collect::<Vec<_>>()
            .join("\n");
        fs::write(&path, text).map_err(|error| format!("无法写入文件：{error}"))?;
    } else {
        let mut writer = create_csv_writer(&path)?;
        writer
            .write_record(melodygap_core::models::MISSING_EXPORT_HEADERS)
            .map_err(|error| error.to_string())?;
        for entry in &entries {
            writer
                .write_record([
                    entry.title.as_str(),
                    entry.artist.as_str(),
                    player_display_name(&entry.player),
                    entry.first_seen.as_str(),
                    entry.last_seen.as_str(),
                    &entry.play_count.to_string(),
                    entry.status_text(),
                ])
                .map_err(|error| error.to_string())?;
        }
        writer.flush().map_err(|error| error.to_string())?;
    }

    let file_name = Path::new(&path)
        .file_name()
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or(path);
    Ok(format!("已导出 {} 首到 {}", entries.len(), file_name))
}

#[tauri::command]
pub fn export_history(
    state: State<'_, AppState>,
    path: String,
    status: String,
    search: String,
) -> Result<String, String> {
    let query = search.trim().to_lowercase();
    let records: Vec<PlayRecord> = state
        .monitor
        .play_history()
        .into_iter()
        .filter(|record| match status.as_str() {
            "in_library" => record.in_library == Some(true),
            "not_in_library" => record.in_library == Some(false),
            "unknown" => record.in_library.is_none(),
            _ => true,
        })
        .filter(|record| {
            if query.is_empty() {
                return true;
            }
            format!(
                "{} {} {} {}",
                record.title,
                record.artist,
                record.player_name(),
                record.status_text()
            )
            .to_lowercase()
            .contains(&query)
        })
        .collect();
    if records.is_empty() {
        return Err("当前筛选条件下没有可导出的记录".to_string());
    }

    let mut writer = create_csv_writer(&path)?;
    writer
        .write_record(melodygap_core::models::CSV_HEADERS)
        .map_err(|error| error.to_string())?;
    for record in &records {
        writer
            .write_record(record.csv_row())
            .map_err(|error| error.to_string())?;
    }
    writer.flush().map_err(|error| error.to_string())?;

    let file_name = Path::new(&path)
        .file_name()
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or(path);
    Ok(format!("已导出 {} 条到 {}", records.len(), file_name))
}

pub fn install_record_callback(app: &AppHandle, state: &AppState) {
    let app_handle = app.clone();
    let callback: melodygap_core::monitor::RecordCallback =
        std::sync::Arc::new(move |record: PlayRecord, _song: SongInfo| {
            let Some(guard) = app_handle.try_state::<AppState>() else {
                return;
            };
            let state = guard.inner().clone();
            let (entry, created) = if record.in_library == Some(false) {
                match state.missing.add_missing(&record) {
                    Ok((entry, created)) => (entry, created),
                    Err(error) => {
                        tracing::error!(%error, "更新待补清单失败");
                        (None, false)
                    }
                }
            } else if record.in_library == Some(true) {
                let _ = state.missing.resolve_song(&record.artist, &record.title);
                (None, false)
            } else {
                (None, false)
            };
            let _ = entry;

            let (mode, cooldown) = {
                let config = state.config.lock().expect("config lock");
                let settings = config.get_app_settings();
                (settings.reminder_mode, settings.reminder_cooldown_minutes)
            };
            let key = make_song_key(&record.artist, &record.title);
            let now = Local::now();
            let last = state
                .last_notified
                .lock()
                .expect("notification history")
                .get(&key)
                .copied();
            if should_notify(&mode, record.in_library, created, last, now, cooldown) {
                state
                    .last_notified
                    .lock()
                    .expect("notification history")
                    .insert(key, now);
                if let Some(notifications) = state.notifications() {
                    notifications.push(NotificationItem {
                        id: 0,
                        title: record.title.clone(),
                        artist: record.artist.clone(),
                        status: record.in_library,
                        player: record.player.clone(),
                        player_name: player_display_name(&record.player).to_string(),
                        is_new_missing: created,
                        copy_text: format!("{} - {}", record.title, record.artist),
                    });
                }
            }

            events::broadcast(&app_handle, &state);
        });
    state.monitor.set_on_record(Some(callback));
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::{create_csv_writer, validate_server_url};

    #[test]
    fn validates_and_normalizes_server_urls() {
        assert_eq!(
            validate_server_url(" https://music.example.com/rest/ ").unwrap(),
            "https://music.example.com"
        );
        assert_eq!(
            validate_server_url("http://127.0.0.1:4533").unwrap(),
            "http://127.0.0.1:4533"
        );
        assert!(validate_server_url("").is_err());
        assert!(validate_server_url("music.example.com").is_err());
    }

    #[test]
    fn csv_writer_adds_bom_and_crlf() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("melodygap-csv-{}-{stamp}.csv", std::process::id()));
        let path_text = path.to_string_lossy().to_string();
        {
            let mut writer = create_csv_writer(&path_text).unwrap();
            writer.write_record(["歌曲", "歌手"]).unwrap();
            writer.flush().unwrap();
        }
        let bytes = fs::read(&path).unwrap();
        let _ = fs::remove_file(&path);
        assert!(bytes.starts_with(&[0xEF, 0xBB, 0xBF]));
        let text = String::from_utf8(bytes[3..].to_vec()).unwrap();
        assert!(text.contains("\r\n"));
        assert!(text.contains("歌曲,歌手"));
    }
}
