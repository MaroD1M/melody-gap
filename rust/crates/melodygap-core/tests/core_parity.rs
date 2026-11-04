use std::fs;
use std::path::Path;

use chrono::{Duration, Local, TimeZone};
use melodygap_core::config::{AppSettings, ConfigManager, SubsonicConfig};
use melodygap_core::constants::{match_player_by_app_id, playback_status_from_code};
use melodygap_core::matcher::{
    calculate_similarity, make_song_key, normalize_text, CandidateSong, SongMatcher,
};
use melodygap_core::missing_repository::MissingRepository;
use melodygap_core::models::{MissingSong, PlayRecord, SongInfo};
use melodygap_core::reminder::should_notify;
use melodygap_core::title_parser::{is_valid_song_title, parse_title, select_best_title};
use serde_json::json;
use tempfile::TempDir;

fn song(title: &str, artist: &str, player: &str) -> SongInfo {
    SongInfo::new(title, artist, player)
}

fn record(
    title: &str,
    artist: &str,
    player: &str,
    in_library: Option<bool>,
    timestamp: &str,
) -> PlayRecord {
    PlayRecord::create_at(
        &song(title, artist, player),
        in_library,
        &format!("{title} - {artist}"),
        Some(timestamp),
    )
}

fn files_with_prefix(dir: &Path, prefix: &str) -> Vec<String> {
    fs::read_dir(dir)
        .unwrap()
        .filter_map(Result::ok)
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter(|name| name.starts_with(prefix))
        .collect()
}

// ---------- title_parser ----------

#[test]
fn title_accepts_separator_titles() {
    for title in [
        "晴天 - 周杰伦",
        "晴天 — 周杰伦",
        "晴天 – 周杰伦",
        "晴天 | 周杰伦",
    ] {
        assert!(is_valid_song_title(title, "netease"), "{title}");
    }
}

#[test]
fn title_accepts_song_containing_function_word() {
    assert!(is_valid_song_title("我的天空 - 南征北战", "qq"));
}

#[test]
fn title_strips_trailing_player_name() {
    assert!(is_valid_song_title("晴天 - 周杰伦 - 网易云音乐", "netease"));
    assert!(is_valid_song_title("晴天 - 周杰伦 - QQ音乐", "qq"));
}

#[test]
fn title_rejects_function_page_segment() {
    assert!(!is_valid_song_title("设置 - 我的", "qq"));
}

#[test]
fn title_rejects_main_window_titles() {
    for title in ["网易云音乐", "QQ音乐", "我的歌单", "设置", "搜索"] {
        assert!(!is_valid_song_title(title, "netease"), "{title}");
    }
}

#[test]
fn title_rejects_player_specific_keyword() {
    assert!(!is_valid_song_title("QQ音乐 - 发现", "qq"));
    assert!(!is_valid_song_title("CloudMusic - 首页", "netease"));
}

#[test]
fn title_rejects_plain_text_without_separator() {
    assert!(!is_valid_song_title("晴天", "qq"));
    assert!(!is_valid_song_title("", "qq"));
}

#[test]
fn title_parses_common_title() {
    let parsed = parse_title("晴天 - 周杰伦", "netease").unwrap();
    assert_eq!(parsed.title, "晴天");
    assert_eq!(parsed.artist, "周杰伦");
    assert_eq!(parsed.player, "netease");
}

#[test]
fn title_parses_all_separators() {
    for title in ["Hello — Adele", "Hello – Adele", "Hello | Adele"] {
        let parsed = parse_title(title, "qq").unwrap_or_else(|| panic!("{title}"));
        assert_eq!(parsed.title, "Hello");
        assert_eq!(parsed.artist, "Adele");
    }
}

#[test]
fn title_parse_returns_none_for_invalid() {
    assert!(parse_title("", "qq").is_none());
    assert!(parse_title("没有分隔符", "qq").is_none());
}

#[test]
fn title_parse_strips_whitespace() {
    let parsed = parse_title("  晴天  -  周杰伦  ", "qq").unwrap();
    assert_eq!(parsed.title, "晴天");
    assert_eq!(parsed.artist, "周杰伦");
}

#[test]
fn title_parse_ignores_trailing_player_name() {
    let parsed = parse_title("晴天 - 周杰伦 - 网易云音乐", "netease").unwrap();
    assert_eq!(parsed.title, "晴天");
    assert_eq!(parsed.artist, "周杰伦");
}

#[test]
fn title_select_best_handles_empty_and_single() {
    assert!(select_best_title(&[]).is_none());
    assert_eq!(
        select_best_title(&["A - B".to_string()]).as_deref(),
        Some("A - B")
    );
}

#[test]
fn title_select_best_prefers_dash_title() {
    let titles = vec![
        "网易云音乐".to_string(),
        "晴天 - 周杰伦".to_string(),
        "晴天 (Live)".to_string(),
    ];
    assert_eq!(select_best_title(&titles).as_deref(), Some("晴天 - 周杰伦"));
}

#[test]
fn title_select_best_penalizes_brackets() {
    let titles = vec![
        "Song - Artist".to_string(),
        "[歌词] Song - Artist".to_string(),
    ];
    assert_eq!(select_best_title(&titles).as_deref(), Some("Song - Artist"));
}

// ---------- matcher ----------

#[test]
fn matcher_normalizes_case_and_punctuation() {
    assert_eq!(normalize_text("Hello, World!"), "hello world");
}

#[test]
fn matcher_removes_english_modifiers() {
    assert_eq!(normalize_text("Song (Live Remix)"), "song");
    assert_eq!(normalize_text("Track [Acoustic]"), "track");
}

#[test]
fn matcher_does_not_break_words_containing_live() {
    assert_eq!(normalize_text("Olive"), "olive");
    assert_eq!(normalize_text("Deliver"), "deliver");
}

#[test]
fn matcher_normalizes_chinese_modifiers() {
    assert_eq!(normalize_text("晴天（现场版）"), "晴天");
    assert_eq!(normalize_text("晴天 伴奏"), "晴天");
}

#[test]
fn matcher_normalizes_fullwidth() {
    assert_eq!(normalize_text("ＡＢＣ　１２３"), "abc 123");
}

#[test]
fn matcher_empty_normalization() {
    assert_eq!(normalize_text(""), "");
}

#[test]
fn matcher_identical_similarity() {
    assert!((calculate_similarity("abc", "abc") - 1.0).abs() < 1e-9);
}

#[test]
fn matcher_empty_similarity() {
    assert_eq!(calculate_similarity("", "abc"), 0.0);
}

#[test]
fn matcher_substring_boost_requires_min_length() {
    assert!(calculate_similarity("a", "abc") < 0.8);
    assert!(calculate_similarity("love", "love story") >= 0.8);
}

#[test]
fn matcher_exact_match() {
    let songs = vec![
        CandidateSong {
            id: "1".into(),
            title: "晴天".into(),
            artist: "周杰伦".into(),
        },
        CandidateSong {
            id: "2".into(),
            title: "稻香".into(),
            artist: "周杰伦".into(),
        },
    ];
    let result = SongMatcher::default().find_best_match(&songs, "周杰伦", "晴天");
    assert!(result.matched);
    assert_eq!(result.song.unwrap().id, "1");
    assert!(result.score >= 0.75);
}

#[test]
fn matcher_match_with_version_suffix() {
    let songs = vec![CandidateSong {
        id: "1".into(),
        title: "晴天 (Live)".into(),
        artist: "周杰伦".into(),
    }];
    assert!(
        SongMatcher::default()
            .find_best_match(&songs, "周杰伦", "晴天")
            .matched
    );
}

#[test]
fn matcher_no_match() {
    let songs = vec![CandidateSong {
        id: "1".into(),
        title: "完全不同的歌".into(),
        artist: "某歌手".into(),
    }];
    let result = SongMatcher::default().find_best_match(&songs, "周杰伦", "晴天");
    assert!(!result.matched);
    assert!(result.song.is_none());
}

#[test]
fn matcher_empty_candidates() {
    let result = SongMatcher::default().find_best_match(&[], "周杰伦", "晴天");
    assert!(!result.matched);
    assert_eq!(result.score, 0.0);
}

#[test]
fn matcher_custom_threshold() {
    let songs = vec![CandidateSong {
        id: "1".into(),
        title: "晴天".into(),
        artist: "周杰伦".into(),
    }];
    let strict = SongMatcher::new(1.01, 0.4, 0.6);
    assert!(!strict.find_best_match(&songs, "周杰伦", "晴天").matched);
}

#[test]
fn matcher_song_key_uses_normalized_fields() {
    assert_eq!(make_song_key("周杰伦", "晴天 (Live)"), "周杰伦|晴天");
}

// ---------- models ----------

#[test]
fn model_song_display_fields() {
    let value = song("晴天", "周杰伦", "qq");
    assert_eq!(value.player_name(), "QQ音乐");
    assert_eq!(value.player_short_name(), "QQ音乐");
    assert_eq!(value.display_text(), "[QQ音乐] 晴天 - 周杰伦");
}

#[test]
fn model_unknown_player_falls_back() {
    let value = song("Song", "Artist", "unknown");
    assert_eq!(value.player_name(), "unknown");
}

#[test]
fn model_play_record_create_with_explicit_timestamp() {
    let value = PlayRecord::create_at(
        &song("晴天", "周杰伦", "netease"),
        Some(true),
        "晴天 - 周杰伦",
        Some("2026-10-20 12:00:00"),
    );
    assert_eq!(value.timestamp, "2026-10-20 12:00:00");
    assert_eq!(value.status_text(), "在曲库");
    assert_eq!(value.player_name(), "网易云音乐");
}

#[test]
fn model_play_record_csv_row() {
    let value = PlayRecord {
        timestamp: "2026-10-20 12:00:00".into(),
        title: "晴天, 现场版".into(),
        artist: "周杰伦".into(),
        in_library: Some(false),
        full_title: "晴天 - 周杰伦".into(),
        player: "qq".into(),
    };
    let row = value.csv_row();
    assert_eq!(row[1], "晴天, 现场版");
    assert_eq!(row[4], "否");
}

#[test]
fn model_play_record_unknown_status() {
    let value = PlayRecord {
        timestamp: "2026-10-20 12:00:00".into(),
        title: "晴天".into(),
        artist: "周杰伦".into(),
        in_library: None,
        full_title: "晴天 - 周杰伦".into(),
        player: "qq".into(),
    };
    assert!(value.is_unknown());
    assert_eq!(value.status_key(), "unknown");
    assert_eq!(value.status_text(), "未知");
    assert_eq!(value.csv_row()[4], "未知");
}

#[test]
fn model_missing_song_display_and_csv() {
    let value = MissingSong {
        key: "周杰伦|晴天".into(),
        title: "晴天".into(),
        artist: "周杰伦".into(),
        player: "qq".into(),
        first_seen: "2026-10-20 12:00:00".into(),
        last_seen: "2026-10-20 12:05:00".into(),
        play_count: 2,
        status: "pending".into(),
    };
    assert_eq!(value.copy_text(), "晴天 - 周杰伦");
    assert_eq!(value.search_query(), "晴天 周杰伦");
    assert_eq!(value.status_text(), "待补");
    assert_eq!(value.csv_row()[5], "2");
}

#[test]
fn model_missing_song_round_trip() {
    let value = MissingSong {
        key: "周杰伦|晴天".into(),
        title: "晴天".into(),
        artist: "周杰伦".into(),
        player: "netease".into(),
        first_seen: "2026-10-20 12:00:00".into(),
        last_seen: "2026-10-20 12:05:00".into(),
        play_count: 3,
        status: "pending".into(),
    };
    assert_eq!(MissingSong::from_dict(value.to_dict()), value);
}

#[test]
fn model_missing_song_defaults_on_invalid_dict() {
    let value = MissingSong::from_dict(json!({
        "key": "周杰伦|晴天",
        "title": "晴天",
        "artist": "周杰伦",
        "play_count": "bad",
        "status": "bad"
    }));
    assert_eq!(value.play_count, 1);
    assert_eq!(value.status, "pending");
}

// ---------- reminder ----------

fn local_time(hour: u32, minute: u32) -> chrono::DateTime<Local> {
    Local
        .with_ymd_and_hms(2026, 10, 20, hour, minute, 0)
        .single()
        .unwrap()
}

#[test]
fn reminder_new_missing_only_notifies_new() {
    let now = local_time(12, 0);
    assert!(should_notify(
        "new_missing",
        Some(false),
        true,
        None,
        now,
        10
    ));
    assert!(!should_notify(
        "new_missing",
        Some(false),
        false,
        None,
        now,
        10
    ));
    assert!(!should_notify(
        "new_missing",
        Some(true),
        true,
        None,
        now,
        10
    ));
}

#[test]
fn reminder_missing_mode_respects_cooldown() {
    let now = local_time(12, 0);
    let last = now - Duration::minutes(5);
    assert!(!should_notify(
        "missing",
        Some(false),
        false,
        Some(last),
        now,
        10
    ));
    assert!(should_notify(
        "missing",
        Some(false),
        false,
        Some(last),
        now,
        0
    ));
    assert!(should_notify(
        "missing",
        Some(false),
        false,
        Some(now - Duration::minutes(11)),
        now,
        10
    ));
}

#[test]
fn reminder_all_mode_notifies_in_library() {
    let now = local_time(12, 0);
    assert!(should_notify("all", Some(true), false, None, now, 10));
    assert!(!should_notify("all", None, false, None, now, 10));
}

#[test]
fn reminder_off_mode_never_notifies() {
    assert!(!should_notify(
        "off",
        Some(false),
        true,
        None,
        local_time(12, 0),
        10
    ));
}

#[test]
fn reminder_unknown_never_notifies() {
    assert!(!should_notify(
        "new_missing",
        None,
        false,
        None,
        local_time(12, 0),
        10
    ));
}

#[test]
fn reminder_invalid_mode_falls_back_to_new_missing() {
    let now = local_time(12, 0);
    assert!(should_notify("bad", Some(false), true, None, now, 10));
    assert!(!should_notify("bad", Some(false), false, None, now, 10));
}

// ---------- config ----------

fn subsonic(server: &str, user: &str, password: &str, verify_ssl: bool) -> SubsonicConfig {
    SubsonicConfig {
        server_url: server.into(),
        username: user.into(),
        password: password.into(),
        verify_ssl,
    }
}

#[test]
fn config_creates_default_config() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let manager = ConfigManager::new(&path).unwrap();
    assert!(path.exists());
    assert!(!manager.is_subsonic_configured());
}

#[test]
fn config_update_and_reload() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    manager
        .update_subsonic_config(&subsonic(
            "https://music.example.com:4533/",
            "demo",
            "secret",
            true,
        ))
        .unwrap();

    let reloaded = ConfigManager::new(&path).unwrap();
    let config = reloaded.get_subsonic_config();
    assert_eq!(config.server_url, "https://music.example.com:4533/");
    assert_eq!(config.username, "demo");
    assert_eq!(config.password, "secret");
    assert!(config.verify_ssl);
    assert!(reloaded.is_subsonic_configured());
}

#[test]
fn config_verify_ssl_can_be_disabled() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    manager
        .update_subsonic_config(&subsonic("https://example.com/", "demo", "secret", false))
        .unwrap();
    assert!(
        !ConfigManager::new(&path)
            .unwrap()
            .get_subsonic_config()
            .verify_ssl
    );
}

#[test]
fn config_password_with_percent_sign() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    manager
        .update_subsonic_config(&subsonic("https://example.com/", "user", "p%ss%word", true))
        .unwrap();
    assert_eq!(
        ConfigManager::new(&path)
            .unwrap()
            .get_subsonic_config()
            .password,
        "p%ss%word"
    );
}

#[test]
fn config_placeholder_is_not_configured() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    manager
        .update_subsonic_config(&subsonic(
            "https://your-server.com:port/",
            "your_username",
            "your_password",
            true,
        ))
        .unwrap();
    assert!(!manager.is_subsonic_configured());
}

#[test]
fn config_reads_utf8_bom() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    fs::write(
        &path,
        "\u{feff}[SUBSONIC]\nserver_url = https://music.example.com/\nusername = demo\npassword = secret\nverify_ssl = 1\n",
    )
    .unwrap();
    let manager = ConfigManager::new(&path).unwrap();
    let config = manager.get_subsonic_config();
    assert_eq!(config.server_url, "https://music.example.com/");
    assert_eq!(config.username, "demo");
    assert!(files_with_prefix(temp.path(), "config.corrupt_").is_empty());
}

#[test]
fn config_corrupt_is_backed_up() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    fs::write(&path, "{not valid ini").unwrap();
    let manager = ConfigManager::new(&path).unwrap();
    assert!(path.exists());
    assert!(!manager.is_subsonic_configured());
    let backups = files_with_prefix(temp.path(), "config.corrupt_");
    assert_eq!(backups.len(), 1);
    assert_eq!(
        fs::read_to_string(temp.path().join(&backups[0])).unwrap(),
        "{not valid ini"
    );
}

#[test]
fn config_missing_file_recreated() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    fs::remove_file(&path).unwrap();
    manager.load().unwrap();
    assert!(path.exists());
}

#[test]
fn config_default_app_settings() {
    let temp = TempDir::new().unwrap();
    let manager = ConfigManager::new(temp.path().join("config.ini")).unwrap();
    let settings = manager.get_app_settings();
    assert_eq!(settings.reminder_mode, "new_missing");
    assert_eq!(settings.reminder_cooldown_minutes, 10);
    assert_eq!(settings.last_tab, 0);
}

#[test]
fn config_update_app_settings_persists() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    let mut settings = manager.get_app_settings();
    settings.reminder_mode = "missing".into();
    settings.reminder_cooldown_minutes = 30;
    settings.last_tab = 1;
    manager.update_app_settings(&settings).unwrap();

    let reloaded = ConfigManager::new(&path).unwrap().get_app_settings();
    assert_eq!(reloaded.reminder_mode, "missing");
    assert_eq!(reloaded.reminder_cooldown_minutes, 30);
    assert_eq!(reloaded.last_tab, 1);
}

#[test]
fn config_invalid_app_settings_fall_back() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    let mut settings = manager.get_app_settings();
    settings.reminder_mode = "unknown".into();
    settings.reminder_cooldown_minutes = -1;
    manager.update_app_settings(&settings).unwrap();
    let loaded = manager.get_app_settings();
    assert_eq!(loaded.reminder_mode, "new_missing");
    assert_eq!(loaded.reminder_cooldown_minutes, 0);
}

#[test]
fn config_cooldown_is_clamped() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    let mut settings = manager.get_app_settings();
    settings.reminder_cooldown_minutes = 9999;
    manager.update_app_settings(&settings).unwrap();
    assert_eq!(manager.get_app_settings().reminder_cooldown_minutes, 1440);

    settings.reminder_cooldown_minutes = -5;
    manager.update_app_settings(&settings).unwrap();
    assert_eq!(manager.get_app_settings().reminder_cooldown_minutes, 0);
}

#[test]
fn config_geometry_and_last_tab_helpers() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("config.ini");
    let mut manager = ConfigManager::new(&path).unwrap();
    manager.set_window_geometry("100x200+10+20", true).unwrap();
    manager.set_last_tab(1).unwrap();
    let loaded = ConfigManager::new(&path).unwrap().get_app_settings();
    assert_eq!(loaded.window_geometry, "100x200+10+20");
    assert!(loaded.window_zoomed);
    assert_eq!(loaded.last_tab, 1);
}

#[test]
fn config_settings_defaults_struct() {
    let defaults = AppSettings::default();
    assert_eq!(defaults.reminder_mode, "new_missing");
    assert_eq!(defaults.reminder_cooldown_minutes, 10);
    assert_eq!(defaults.last_tab, 0);
}

// ---------- missing repository ----------

fn repository() -> (TempDir, MissingRepository) {
    let temp = TempDir::new().unwrap();
    let repo = MissingRepository::new(temp.path().join("missing_songs.json"));
    (temp, repo)
}

#[test]
fn repository_add_and_deduplicate() {
    let (_temp, repo) = repository();
    let (entry, created) = repo
        .add_missing(&record(
            "晴天",
            "周杰伦",
            "qq",
            Some(false),
            "2026-10-20 12:00:00",
        ))
        .unwrap();
    assert!(created);
    assert_eq!(entry.unwrap().play_count, 1);

    let (entry, created) = repo
        .add_missing(&record(
            "晴天",
            "周杰伦",
            "netease",
            Some(false),
            "2026-10-20 12:05:00",
        ))
        .unwrap();
    assert!(!created);
    let entry = entry.unwrap();
    assert_eq!(entry.play_count, 2);
    assert_eq!(entry.last_seen, "2026-10-20 12:05:00");
    assert_eq!(repo.count_pending(), 1);
}

#[test]
fn repository_ensure_missing_does_not_count_recheck_as_play() {
    let (_temp, repo) = repository();
    let (entry, created) = repo
        .add_missing(&record(
            "晴天",
            "周杰伦",
            "qq",
            Some(false),
            "2026-10-20 12:00:00",
        ))
        .unwrap();
    assert!(created);
    let entry = entry.unwrap();

    let (same, created) = repo
        .ensure_missing(&record(
            "晴天",
            "周杰伦",
            "netease",
            Some(false),
            "2026-10-20 12:05:00",
        ))
        .unwrap();
    assert!(!created);
    let same = same.unwrap();
    assert_eq!(same.key, entry.key);
    assert_eq!(same.play_count, 1);
    assert_eq!(same.last_seen, "2026-10-20 12:00:00");
    assert_eq!(same.player, "qq");
}

#[test]
fn repository_ensure_missing_inserts_new_record() {
    let (_temp, repo) = repository();
    let (entry, created) = repo
        .ensure_missing(&record(
            "晴天",
            "周杰伦",
            "qq",
            Some(false),
            "2026-10-20 12:00:00",
        ))
        .unwrap();
    assert!(created);
    assert_eq!(entry.unwrap().play_count, 1);
    assert_eq!(repo.count_pending(), 1);
}

#[test]
fn repository_only_missing_records_are_added() {
    let (_temp, repo) = repository();
    repo.add_missing(&record(
        "晴天",
        "周杰伦",
        "qq",
        Some(true),
        "2026-10-20 12:00:00",
    ))
    .unwrap();
    repo.add_missing(&record("晴天", "周杰伦", "qq", None, "2026-10-20 12:00:00"))
        .unwrap();
    assert!(repo.snapshot().is_empty());
}

#[test]
fn repository_persists_across_reload() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("missing_songs.json");
    let repo = MissingRepository::new(&path);
    repo.add_missing(&record(
        "晴天",
        "周杰伦",
        "qq",
        Some(false),
        "2026-10-20 12:00:00",
    ))
    .unwrap();
    let entries = MissingRepository::new(&path).snapshot();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].title, "晴天");
    assert_eq!(entries[0].status, "pending");
}

#[test]
fn repository_ignore_and_restore() {
    let (_temp, repo) = repository();
    let (entry, _) = repo
        .add_missing(&record(
            "晴天",
            "周杰伦",
            "qq",
            Some(false),
            "2026-10-20 12:00:00",
        ))
        .unwrap();
    let key = entry.unwrap().key;
    assert!(repo.set_status(&key, "ignored").unwrap());
    assert_eq!(repo.count_pending(), 0);
    assert_eq!(repo.get(&key).unwrap().status, "ignored");
    assert!(repo.set_status(&key, "pending").unwrap());
    assert_eq!(repo.count_pending(), 1);
}

#[test]
fn repository_batch_status_and_remove() {
    let (_temp, repo) = repository();
    let keys: Vec<String> = ["晴天", "夜曲", "稻香"]
        .iter()
        .map(|title| {
            repo.add_missing(&record(
                title,
                "周杰伦",
                "qq",
                Some(false),
                "2026-10-20 12:00:00",
            ))
            .unwrap()
            .0
            .unwrap()
            .key
        })
        .collect();

    assert_eq!(repo.set_status_many(&keys[..2], "ignored").unwrap(), 2);
    assert_eq!(repo.set_status_many(&keys[..2], "ignored").unwrap(), 0);
    assert_eq!(repo.count_pending(), 1);
    assert_eq!(repo.remove_many(&keys).unwrap(), 3);
    assert!(repo.snapshot().is_empty());
}

#[test]
fn repository_resolve_song() {
    let (_temp, repo) = repository();
    let (entry, _) = repo
        .add_missing(&record(
            "晴天",
            "周杰伦",
            "qq",
            Some(false),
            "2026-10-20 12:00:00",
        ))
        .unwrap();
    assert!(repo.resolve_song("周杰伦", "晴天").unwrap());
    assert!(repo.get(&entry.unwrap().key).is_none());
    assert!(!repo.resolve_song("周杰伦", "晴天").unwrap());
}

#[test]
fn repository_remove_and_clear() {
    let (_temp, repo) = repository();
    let (entry, _) = repo
        .add_missing(&record(
            "晴天",
            "周杰伦",
            "qq",
            Some(false),
            "2026-10-20 12:00:00",
        ))
        .unwrap();
    assert!(repo.remove_key(&entry.unwrap().key).unwrap());
    assert!(repo.snapshot().is_empty());

    repo.add_missing(&record(
        "晴天",
        "周杰伦",
        "qq",
        Some(false),
        "2026-10-20 12:00:00",
    ))
    .unwrap();
    repo.clear().unwrap();
    assert!(repo.snapshot().is_empty());
}

#[test]
fn repository_corrupt_file_is_backed_up() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("missing_songs.json");
    fs::write(&path, "{not valid json").unwrap();
    let repo = MissingRepository::new(&path);
    assert!(repo.snapshot().is_empty());
    assert_eq!(
        files_with_prefix(temp.path(), "missing_songs.corrupt_").len(),
        1
    );
    assert!(!path.exists());
}

#[test]
fn repository_invalid_play_count_is_normalized() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("missing_songs.json");
    fs::write(
        &path,
        serde_json::to_string(&json!({
            "songs": [{
                "key": "周杰伦|晴天",
                "title": "晴天",
                "artist": "周杰伦",
                "player": "qq",
                "first_seen": "2026-10-20 12:00:00",
                "last_seen": "2026-10-20 12:00:00",
                "play_count": "not-a-number",
                "status": "pending"
            }]
        }))
        .unwrap(),
    )
    .unwrap();
    let repo = MissingRepository::new(&path);
    assert_eq!(repo.snapshot()[0].play_count, 1);
}

#[test]
fn repository_unknown_status_is_normalized() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("missing_songs.json");
    fs::write(
        &path,
        serde_json::to_string(&json!({
            "songs": [{
                "key": "周杰伦|晴天",
                "title": "晴天",
                "artist": "周杰伦",
                "player": "qq",
                "first_seen": "2026-10-20 12:00:00",
                "last_seen": "2026-10-20 12:00:00",
                "play_count": 1,
                "status": "bad-status"
            }]
        }))
        .unwrap(),
    )
    .unwrap();
    let repo = MissingRepository::new(&path);
    assert_eq!(repo.snapshot()[0].status, "pending");
}

#[test]
fn repository_accepts_array_payload_and_backfills_key() {
    let temp = TempDir::new().unwrap();
    let path = temp.path().join("missing_songs.json");
    fs::write(
        &path,
        serde_json::to_string(&json!([{
            "title": "晴天",
            "artist": "周杰伦",
            "player": "qq",
            "first_seen": "2026-10-20 12:00:00",
            "last_seen": "2026-10-20 12:00:00"
        }]))
        .unwrap(),
    )
    .unwrap();
    let entries = MissingRepository::new(&path).snapshot();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].key, "周杰伦|晴天");
    assert_eq!(entries[0].play_count, 1);
}

#[test]
fn repository_rejects_invalid_status_write() {
    let (_temp, repo) = repository();
    assert!(repo.set_status("missing", "bad").is_err());
}

#[test]
fn matcher_matches_python_difflib_golden_cases() {
    let cases = [
        ("晴天", "晴天", 1.0),
        ("周杰伦", "周杰倫", 0.666666666667),
        ("abc", "abd", 0.666666666667),
        ("kitten", "sitting", 0.615384615385),
        ("love", "love story", 0.8),
        ("hello world", "hello there world", 0.785714285714),
        ("a", "abc", 0.5),
        ("abcde", "abc", 0.75),
        ("你好世界", "你好", 0.666666666667),
        ("a b c", "abc", 0.75),
        ("晴天", "晴天 周杰伦", 0.5),
        ("周杰伦 晴天", "周杰伦晴天", 0.909090909091),
        ("track 01", "track 02", 0.875),
        ("deliver", "", 0.0),
        ("abcdef", "abcxyz", 0.5),
    ];
    for (left, right, expected) in cases {
        let actual = calculate_similarity(left, right);
        assert!(
            (actual - expected).abs() < 1e-9,
            "{left:?} vs {right:?}: expected {expected}, got {actual}"
        );
    }
}

#[test]
fn matcher_normalized_golden_pipeline() {
    let cases = [
        ("Song (Live Remix)", "song"),
        ("Track [Acoustic]", "track"),
        ("晴天（现场版）", "晴天"),
        ("晴天 伴奏", "晴天"),
        ("ＡＢＣ　１２３", "abc 123"),
        ("Olive", "olive"),
        ("Deliver", "deliver"),
        ("Hello, World!", "hello world"),
        ("Love Story", "love story"),
    ];
    for (input, expected) in cases {
        assert_eq!(normalize_text(input), expected, "{input:?}");
    }
}

#[test]
fn smtc_matches_player_by_app_id() {
    assert_eq!(match_player_by_app_id("Tencent.QQMusicPC"), Some("qq"));
    assert_eq!(match_player_by_app_id("QQMusic.exe"), Some("qq"));
    assert_eq!(match_player_by_app_id("CloudMusic.exe"), Some("netease"));
    assert_eq!(
        match_player_by_app_id("Netease.CloudMusic"),
        Some("netease")
    );
    assert_eq!(match_player_by_app_id("Spotify.exe"), None);
    assert_eq!(match_player_by_app_id(""), None);
}

#[test]
fn smtc_normalizes_playback_status_codes() {
    assert_eq!(playback_status_from_code(4), "playing");
    assert_eq!(playback_status_from_code(5), "paused");
    assert_eq!(playback_status_from_code(3), "stopped");
    assert_eq!(playback_status_from_code(0), "unknown");
    assert_eq!(playback_status_from_code(99), "unknown");
}
