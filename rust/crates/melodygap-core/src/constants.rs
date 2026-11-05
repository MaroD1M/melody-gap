//! 全局常量。保持与 v1.x 历史实现同值，避免行为回归。

pub const APP_NAME: &str = "MelodyGap";
pub const APP_DISPLAY_NAME: &str = "MelodyGap 曲库补漏";
pub const APP_VERSION: &str = "2.0.2";
pub const CONFIG_FILE_NAME: &str = "config.ini";
pub const LOG_FILE_NAME: &str = "melodygap.log";
pub const MISSING_FILE_NAME: &str = "missing_songs.json";

#[derive(Clone, Copy, Debug)]
pub struct PlayerConfig {
    pub key: &'static str,
    pub display_name: &'static str,
    pub short_name: &'static str,
    pub processes: &'static [&'static str],
    pub smtc_app_ids: &'static [&'static str],
}

pub const SUPPORTED_PLAYERS: &[PlayerConfig] = &[
    PlayerConfig {
        key: "qq",
        display_name: "QQ音乐",
        short_name: "QQ音乐",
        processes: &["qqmusic.exe"],
        smtc_app_ids: &["qqmusic", "tencent.qqmusic", "tencent.qqmusicpc"],
    },
    PlayerConfig {
        key: "netease",
        display_name: "网易云音乐",
        short_name: "网易云",
        processes: &[
            "cloudmusic.exe",
            "neteasecloudmusic.exe",
            "neteasemusic.exe",
        ],
        smtc_app_ids: &["cloudmusic", "neteasecloudmusic", "netease.cloudmusic"],
    },
];

pub fn player_config(key: &str) -> Option<&'static PlayerConfig> {
    SUPPORTED_PLAYERS.iter().find(|item| item.key == key)
}

pub fn player_display_name(key: &str) -> &str {
    player_config(key)
        .map(|item| item.display_name)
        .unwrap_or(key)
}

pub fn player_short_name(key: &str) -> &str {
    player_config(key)
        .map(|item| item.short_name)
        .unwrap_or(key)
}

/// 把 SMTC 的 AppUserModelId 映射到项目内的播放器标识。
pub fn match_player_by_app_id(app_id: &str) -> Option<&'static str> {
    let lowered = app_id.trim().to_lowercase();
    if lowered.is_empty() {
        return None;
    }
    for player in SUPPORTED_PLAYERS {
        for alias in player.smtc_app_ids.iter().chain(player.processes.iter()) {
            if !alias.is_empty() && lowered.contains(&alias.to_lowercase()) {
                return Some(player.key);
            }
        }
    }
    None
}

/// 把 SMTC 播放状态枚举的数值统一为字符串。
pub fn playback_status_from_code(code: i32) -> &'static str {
    match code {
        4 => PLAYBACK_STATUS_PLAYING,
        5 => PLAYBACK_STATUS_PAUSED,
        3 => PLAYBACK_STATUS_STOPPED,
        _ => PLAYBACK_STATUS_UNKNOWN,
    }
}

pub const PLAYBACK_SOURCE_SMTC: &str = "smtc";
pub const PLAYBACK_SOURCE_WINDOW: &str = "window";
pub const PLAYBACK_STATUS_PLAYING: &str = "playing";
pub const PLAYBACK_STATUS_PAUSED: &str = "paused";
pub const PLAYBACK_STATUS_STOPPED: &str = "stopped";
pub const PLAYBACK_STATUS_UNKNOWN: &str = "unknown";

pub const SMTC_POLL_INTERVAL_SECONDS: f64 = 2.0;
pub const SMTC_REQUEST_TIMEOUT_SECONDS: f64 = 3.0;
pub const SMTC_METADATA_TIMEOUT_SECONDS: f64 = 2.5;

pub const EXCLUDED_TITLE_KEYWORDS: &[&str] = &[
    "设置",
    "搜索",
    "登录",
    "选项",
    "偏好",
    "关于",
    "帮助",
    "更新",
    "歌单",
    "我的歌单",
    "我的音乐",
    "我的收藏",
    "播放列表",
    "本地音乐",
    "下载管理",
    "发现音乐",
    "每日推荐",
    "私人漫游",
    "云盘",
    "历史记录",
];

pub const PLAYER_EXCLUDED_KEYWORDS_QQ: &[&str] = &["QQ音乐", "QQMusic"];
pub const PLAYER_EXCLUDED_KEYWORDS_NETEASE: &[&str] = &["网易云音乐", "NetEase", "CloudMusic"];

pub const PLAYER_TITLE_SUFFIXES_QQ: &[&str] = &["QQ音乐", "QQMusic"];
pub const PLAYER_TITLE_SUFFIXES_NETEASE: &[&str] = &[
    "网易云音乐",
    "网易云",
    "NetEase",
    "NetEase Cloud Music",
    "CloudMusic",
];

pub const TITLE_SEPARATORS: &[&str] = &[" - ", " — ", " – ", " | "];
pub const TITLE_PATTERNS: &[&str] = &[
    r"^(.+?)\s*-\s*(.+?)$",
    r"^(.+?)\s*—\s*(.+?)$",
    r"^(.+?)\s*–\s*(.+?)$",
    r"^(.+?)\s*\|\s*(.+?)$",
];

pub const SUBSONIC_API_VERSION: &str = "1.16.1";
pub const SUBSONIC_CLIENT_NAME: &str = "MelodyGap";
pub const SUBSONIC_REQUEST_TIMEOUT: u64 = 10;
pub const SUBSONIC_SONG_COUNT_FULL: u32 = 50;
pub const SUBSONIC_SONG_COUNT_SINGLE: u32 = 30;
pub const SUBSONIC_PLACEHOLDER_SERVER: &str = "https://your-server.com";
pub const SUBSONIC_SECTION: &str = "SUBSONIC";
pub const APP_SECTION: &str = "APP";

pub const MATCH_THRESHOLD: f64 = 0.75;
pub const EARLY_STOP_SCORE: f64 = 0.90;
pub const ARTIST_WEIGHT: f64 = 0.4;
pub const TITLE_WEIGHT: f64 = 0.6;
pub const SUBSTRING_MIN_LENGTH: usize = 4;
pub const SUBSTRING_SCORE: f64 = 0.8;

pub const MODIFIER_WORDS_EN: &[&str] = &[
    "remix",
    "remaster",
    "remastered",
    "acoustic",
    "live",
    "demo",
    "instrumental",
    "cover",
    "feat",
    "ft",
    "featuring",
];

pub const MODIFIER_WORDS_ZH: &[&str] = &["重制版", "混音版", "伴奏", "现场版"];

pub const MONITOR_INTERVAL_SECONDS: f64 = 2.0;
pub const MONITOR_STOP_TIMEOUT_SECONDS: f64 = 3.0;
pub const PLAYER_STATE_RESET_SECONDS: f64 = 10.0;
pub const UNKNOWN_RETRY_SECONDS: f64 = 15.0;
pub const UNKNOWN_RETRY_MAX: u32 = 5;

pub const MISSING_STATUS_PENDING: &str = "pending";
pub const MISSING_STATUS_IGNORED: &str = "ignored";

pub fn is_valid_missing_status(status: &str) -> bool {
    status == MISSING_STATUS_PENDING || status == MISSING_STATUS_IGNORED
}

pub fn missing_status_text(status: &str) -> &str {
    match status {
        MISSING_STATUS_PENDING => "待补",
        MISSING_STATUS_IGNORED => "已忽略",
        other => other,
    }
}

pub const REMINDER_MODE_NEW_MISSING: &str = "new_missing";
pub const REMINDER_MODE_MISSING: &str = "missing";
pub const REMINDER_MODE_ALL: &str = "all";
pub const REMINDER_MODE_OFF: &str = "off";
pub const DEFAULT_REMINDER_MODE: &str = REMINDER_MODE_NEW_MISSING;
pub const DEFAULT_REMINDER_COOLDOWN_MINUTES: i64 = 10;
pub const DEFAULT_LAST_TAB: i64 = 0;

pub fn is_valid_reminder_mode(mode: &str) -> bool {
    matches!(
        mode,
        REMINDER_MODE_NEW_MISSING | REMINDER_MODE_MISSING | REMINDER_MODE_ALL | REMINDER_MODE_OFF
    )
}
