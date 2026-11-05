//! 领域数据模型，字段语义保持与 v1.x 兼容。

use chrono::Local;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;

use crate::constants::{
    is_valid_missing_status, missing_status_text, player_display_name, player_short_name,
    MISSING_STATUS_PENDING,
};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SongInfo {
    pub title: String,
    pub artist: String,
    pub player: String,
}

impl SongInfo {
    pub fn new(
        title: impl Into<String>,
        artist: impl Into<String>,
        player: impl Into<String>,
    ) -> Self {
        Self {
            title: title.into(),
            artist: artist.into(),
            player: player.into(),
        }
    }

    pub fn player_name(&self) -> &str {
        player_display_name(&self.player)
    }

    pub fn player_short_name(&self) -> &str {
        player_short_name(&self.player)
    }

    pub fn display_text(&self) -> String {
        format!("[{}] {} - {}", self.player_name(), self.title, self.artist)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct PlaybackCandidate {
    pub song: SongInfo,
    pub source: String,
    pub playback_status: String,
    pub full_title: String,
}

impl PlaybackCandidate {
    pub fn player(&self) -> &str {
        &self.song.player
    }

    pub fn title(&self) -> &str {
        &self.song.title
    }

    pub fn artist(&self) -> &str {
        &self.song.artist
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct PlayRecord {
    pub timestamp: String,
    pub title: String,
    pub artist: String,
    pub in_library: Option<bool>,
    pub full_title: String,
    pub player: String,
}

impl PlayRecord {
    pub fn create(song: &SongInfo, in_library: Option<bool>, full_title: &str) -> Self {
        Self::create_at(song, in_library, full_title, None)
    }

    pub fn create_at(
        song: &SongInfo,
        in_library: Option<bool>,
        full_title: &str,
        timestamp: Option<&str>,
    ) -> Self {
        Self {
            timestamp: timestamp
                .map(ToString::to_string)
                .unwrap_or_else(|| Local::now().format("%Y-%m-%d %H:%M:%S").to_string()),
            title: song.title.clone(),
            artist: song.artist.clone(),
            in_library,
            full_title: full_title.to_string(),
            player: song.player.clone(),
        }
    }

    pub fn status_key(&self) -> &'static str {
        match self.in_library {
            None => "unknown",
            Some(true) => "in_library",
            Some(false) => "not_in_library",
        }
    }

    pub fn status_text(&self) -> &'static str {
        match self.in_library {
            None => "未知",
            Some(true) => "在曲库",
            Some(false) => "不在库",
        }
    }

    pub fn is_missing(&self) -> bool {
        self.in_library == Some(false)
    }

    pub fn is_unknown(&self) -> bool {
        self.in_library.is_none()
    }

    pub fn player_name(&self) -> &str {
        player_display_name(&self.player)
    }

    pub fn player_short_name(&self) -> &str {
        player_short_name(&self.player)
    }

    pub fn csv_row(&self) -> Vec<String> {
        let in_library_text = match self.in_library {
            None => "未知",
            Some(true) => "是",
            Some(false) => "否",
        };
        vec![
            self.timestamp.clone(),
            self.title.clone(),
            self.artist.clone(),
            self.player_name().to_string(),
            in_library_text.to_string(),
        ]
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MissingSong {
    #[serde(default)]
    pub key: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub artist: String,
    #[serde(default)]
    pub player: String,
    #[serde(default)]
    pub first_seen: String,
    #[serde(default)]
    pub last_seen: String,
    #[serde(
        default = "default_play_count",
        deserialize_with = "deserialize_play_count"
    )]
    pub play_count: i64,
    #[serde(default = "default_status")]
    pub status: String,
}

fn default_play_count() -> i64 {
    1
}

fn deserialize_play_count<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    Ok(match value {
        Value::Number(number) => number.as_i64().unwrap_or(1),
        Value::String(text) => text.parse::<i64>().unwrap_or(1),
        _ => 1,
    })
}

fn default_status() -> String {
    MISSING_STATUS_PENDING.to_string()
}

impl MissingSong {
    pub fn player_name(&self) -> &str {
        player_display_name(&self.player)
    }

    pub fn player_short_name(&self) -> &str {
        player_short_name(&self.player)
    }

    pub fn status_text(&self) -> &str {
        missing_status_text(&self.status)
    }

    pub fn is_pending(&self) -> bool {
        self.status == MISSING_STATUS_PENDING
    }

    pub fn copy_text(&self) -> String {
        format!("{} - {}", self.title, self.artist)
    }

    pub fn search_query(&self) -> String {
        format!("{} {}", self.title, self.artist).trim().to_string()
    }

    pub fn normalize(mut self) -> Self {
        self.play_count = self.play_count.max(1);
        if !is_valid_missing_status(&self.status) {
            self.status = MISSING_STATUS_PENDING.to_string();
        }
        self
    }

    pub fn csv_row(&self) -> Vec<String> {
        vec![
            self.title.clone(),
            self.artist.clone(),
            self.player_name().to_string(),
            self.first_seen.clone(),
            self.last_seen.clone(),
            self.play_count.to_string(),
            self.status_text().to_string(),
        ]
    }

    pub fn to_dict(&self) -> Value {
        serde_json::to_value(self).unwrap_or(Value::Null)
    }

    pub fn from_dict(value: Value) -> Self {
        serde_json::from_value::<Self>(value)
            .unwrap_or_else(|_| Self {
                key: String::new(),
                title: String::new(),
                artist: String::new(),
                player: String::new(),
                first_seen: String::new(),
                last_seen: String::new(),
                play_count: 1,
                status: MISSING_STATUS_PENDING.to_string(),
            })
            .normalize()
    }
}

pub const CSV_HEADERS: [&str; 5] = ["播放时间", "歌曲名称", "歌手", "播放器", "在曲库中"];
pub const MISSING_EXPORT_HEADERS: [&str; 7] = [
    "歌曲名称",
    "歌手",
    "播放器",
    "首次发现",
    "最后发现",
    "发现次数",
    "状态",
];
