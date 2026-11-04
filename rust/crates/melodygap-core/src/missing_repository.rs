//! 待补清单本地持久化。

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::sync::Mutex;

use chrono::Local;
use thiserror::Error;

use crate::constants::{is_valid_missing_status, MISSING_STATUS_PENDING};
use crate::matcher::make_song_key;
use crate::models::{MissingSong, PlayRecord};

#[derive(Debug, Error)]
pub enum RepositoryError {
    #[error("待补清单读写失败: {0}")]
    Io(#[from] io::Error),
    #[error("待补清单序列化失败: {0}")]
    Json(#[from] serde_json::Error),
    #[error("未知的待补状态: {0}")]
    InvalidStatus(String),
}

#[derive(Debug)]
pub struct MissingRepository {
    path: PathBuf,
    entries: Mutex<BTreeMap<String, MissingSong>>,
}

impl MissingRepository {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        let repository = Self {
            path: path.into(),
            entries: Mutex::new(BTreeMap::new()),
        };
        repository.load();
        repository
    }

    pub fn path(&self) -> &std::path::Path {
        &self.path
    }

    pub fn load(&self) {
        let mut entries = self.entries.lock().expect("repository lock");
        entries.clear();
        if !self.path.exists() {
            return;
        }

        let bytes = match fs::read(&self.path) {
            Ok(value) => value,
            Err(error) => {
                tracing::error!(%error, "读取待补清单失败");
                self.backup_corrupt_locked();
                return;
            }
        };

        let value: serde_json::Value = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(error) => {
                tracing::error!(%error, "待补清单 JSON 损坏");
                self.backup_corrupt_locked();
                return;
            }
        };

        let raw_entries = if value.is_array() {
            value.as_array().cloned().unwrap_or_default()
        } else if let Some(songs) = value.get("songs").and_then(|item| item.as_array()) {
            songs.clone()
        } else {
            tracing::warn!("待补清单格式不正确，将使用空清单");
            self.backup_corrupt_locked();
            return;
        };

        for raw in raw_entries {
            let Some(object) = raw.as_object() else {
                continue;
            };
            let mut entry: MissingSong = match serde_json::from_value::<MissingSong>(
                serde_json::Value::Object(object.clone()),
            ) {
                Ok(value) => value.normalize(),
                Err(_) => continue,
            };
            if entry.title.is_empty() || entry.artist.is_empty() {
                continue;
            }
            if entry.key.is_empty() {
                entry.key = make_song_key(&entry.artist, &entry.title);
            }
            if !is_valid_missing_status(&entry.status) {
                entry.status = MISSING_STATUS_PENDING.to_string();
            }
            entries.insert(entry.key.clone(), entry);
        }

        tracing::info!(count = entries.len(), "待补清单已加载");
    }

    fn backup_corrupt_locked(&self) {
        if !self.path.exists() {
            return;
        }
        let suffix = Local::now().format("%Y%m%d_%H%M%S").to_string();
        let stem = self
            .path
            .file_stem()
            .map(|value| value.to_string_lossy().to_string())
            .unwrap_or_else(|| "missing_songs".to_string());
        let backup = self
            .path
            .with_file_name(format!("{stem}.corrupt_{suffix}.json"));
        if let Err(error) = fs::rename(&self.path, &backup) {
            tracing::error!(%error, "备份损坏的待补清单失败");
        } else {
            tracing::warn!(path = %backup.display(), "损坏的待补清单已备份");
        }
    }

    fn save_locked(&self, entries: &BTreeMap<String, MissingSong>) -> Result<(), RepositoryError> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut songs: Vec<&MissingSong> = entries.values().collect();
        songs.sort_by(|left, right| left.first_seen.cmp(&right.first_seen));

        let payload = serde_json::json!({
            "version": 1,
            "songs": songs,
        });
        let text = serde_json::to_string_pretty(&payload)?;
        let temp_path = self.path.with_file_name(format!(
            "{}.tmp",
            self.path
                .file_name()
                .map(|value| value.to_string_lossy().to_string())
                .unwrap_or_else(|| "missing_songs.json".to_string())
        ));
        fs::write(&temp_path, text.as_bytes())?;
        if let Err(error) = fs::rename(&temp_path, &self.path) {
            let _ = fs::remove_file(&self.path);
            if let Err(second) = fs::rename(&temp_path, &self.path) {
                let _ = fs::remove_file(&temp_path);
                return Err(RepositoryError::Io(
                    if second.kind() == io::ErrorKind::NotFound {
                        error
                    } else {
                        second
                    },
                ));
            }
        }
        Ok(())
    }

    pub fn snapshot(&self) -> Vec<MissingSong> {
        let entries = self.entries.lock().expect("repository lock");
        entries.values().cloned().collect()
    }

    pub fn get(&self, key: &str) -> Option<MissingSong> {
        self.entries
            .lock()
            .expect("repository lock")
            .get(key)
            .cloned()
    }

    pub fn count_pending(&self) -> usize {
        self.entries
            .lock()
            .expect("repository lock")
            .values()
            .filter(|entry| entry.is_pending())
            .count()
    }

    pub fn add_missing(
        &self,
        record: &PlayRecord,
    ) -> Result<(Option<MissingSong>, bool), RepositoryError> {
        self.add_missing_inner(record, true)
    }

    pub fn ensure_missing(
        &self,
        record: &PlayRecord,
    ) -> Result<(Option<MissingSong>, bool), RepositoryError> {
        self.add_missing_inner(record, false)
    }

    fn add_missing_inner(
        &self,
        record: &PlayRecord,
        count_play: bool,
    ) -> Result<(Option<MissingSong>, bool), RepositoryError> {
        if record.in_library != Some(false) {
            return Ok((None, false));
        }

        let key = make_song_key(&record.artist, &record.title);
        let mut entries = self.entries.lock().expect("repository lock");
        if entries.contains_key(&key) {
            let updated = if count_play {
                let existing = entries.get_mut(&key).expect("entry exists");
                existing.last_seen = record.timestamp.clone();
                existing.play_count += 1;
                let clone = existing.clone();
                self.save_locked(&entries)?;
                clone
            } else {
                entries.get(&key).expect("entry exists").clone()
            };
            return Ok((Some(updated), false));
        }

        let entry = MissingSong {
            key: key.clone(),
            title: record.title.clone(),
            artist: record.artist.clone(),
            player: record.player.clone(),
            first_seen: record.timestamp.clone(),
            last_seen: record.timestamp.clone(),
            play_count: 1,
            status: MISSING_STATUS_PENDING.to_string(),
        };
        entries.insert(key, entry.clone());
        self.save_locked(&entries)?;
        Ok((Some(entry), true))
    }

    pub fn resolve_song(&self, artist: &str, title: &str) -> Result<bool, RepositoryError> {
        self.remove_key(&make_song_key(artist, title))
    }

    pub fn remove_key(&self, key: &str) -> Result<bool, RepositoryError> {
        let mut entries = self.entries.lock().expect("repository lock");
        if entries.remove(key).is_none() {
            return Ok(false);
        }
        self.save_locked(&entries)?;
        Ok(true)
    }

    pub fn set_status(&self, key: &str, status: &str) -> Result<bool, RepositoryError> {
        if !is_valid_missing_status(status) {
            return Err(RepositoryError::InvalidStatus(status.to_string()));
        }
        let mut entries = self.entries.lock().expect("repository lock");
        let Some(entry) = entries.get_mut(key) else {
            return Ok(false);
        };
        entry.status = status.to_string();
        self.save_locked(&entries)?;
        Ok(true)
    }

    pub fn set_status_many(&self, keys: &[String], status: &str) -> Result<usize, RepositoryError> {
        if !is_valid_missing_status(status) {
            return Err(RepositoryError::InvalidStatus(status.to_string()));
        }
        let mut entries = self.entries.lock().expect("repository lock");
        let mut updated = 0usize;
        for key in keys {
            let Some(entry) = entries.get_mut(key) else {
                continue;
            };
            if entry.status == status {
                continue;
            }
            entry.status = status.to_string();
            updated += 1;
        }
        if updated > 0 {
            self.save_locked(&entries)?;
        }
        Ok(updated)
    }

    pub fn remove_many(&self, keys: &[String]) -> Result<usize, RepositoryError> {
        let mut entries = self.entries.lock().expect("repository lock");
        let mut removed = 0usize;
        for key in keys {
            if entries.remove(key).is_some() {
                removed += 1;
            }
        }
        if removed > 0 {
            self.save_locked(&entries)?;
        }
        Ok(removed)
    }

    pub fn clear(&self) -> Result<(), RepositoryError> {
        let mut entries = self.entries.lock().expect("repository lock");
        entries.clear();
        self.save_locked(&entries)
    }
}
