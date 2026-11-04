use std::sync::{Arc, Mutex};
use std::time::Duration;

use melodygap_core::config::ConfigManager;
use melodygap_core::constants::{PLAYBACK_SOURCE_SMTC, PLAYBACK_SOURCE_WINDOW};
use melodygap_core::models::{PlayRecord, PlaybackCandidate, SongInfo};
use melodygap_core::monitor::{MusicMonitor, PlaybackDetector, RecordCallback};
use melodygap_core::subsonic::{LibraryClient, ServerInfo, SubsonicError};
use tempfile::TempDir;

#[derive(Clone)]
struct FakeDetector {
    candidates: Arc<Mutex<Vec<PlaybackCandidate>>>,
}

impl FakeDetector {
    fn new() -> Self {
        Self {
            candidates: Arc::new(Mutex::new(Vec::new())),
        }
    }

    fn set(&self, candidates: Vec<PlaybackCandidate>) {
        *self.candidates.lock().unwrap() = candidates;
    }
}

impl PlaybackDetector for FakeDetector {
    fn get_current_playings(&mut self) -> Vec<PlaybackCandidate> {
        self.candidates.lock().unwrap().clone()
    }
}

#[derive(Clone, Default)]
struct FakeLibrary {
    calls: Arc<Mutex<Vec<(String, String)>>>,
    result: Arc<Mutex<bool>>,
    error: Arc<Mutex<Option<String>>>,
}

impl FakeLibrary {
    fn set_result(&self, value: bool) {
        *self.result.lock().unwrap() = value;
    }

    fn set_error(&self, value: Option<&str>) {
        *self.error.lock().unwrap() = value.map(ToString::to_string);
    }

    fn calls(&self) -> Vec<(String, String)> {
        self.calls.lock().unwrap().clone()
    }
}

impl LibraryClient for FakeLibrary {
    fn find_exact_match(&self, artist: &str, title: &str) -> Result<bool, SubsonicError> {
        self.calls
            .lock()
            .unwrap()
            .push((artist.to_string(), title.to_string()));
        if let Some(error) = self.error.lock().unwrap().clone() {
            return Err(SubsonicError::new(error, -1));
        }
        Ok(*self.result.lock().unwrap())
    }

    fn ping(&self) -> Result<ServerInfo, SubsonicError> {
        Ok(ServerInfo::default())
    }
}

struct Harness {
    _temp: TempDir,
    monitor: MusicMonitor,
    detector: FakeDetector,
    library: FakeLibrary,
    records: Arc<Mutex<Vec<(PlayRecord, SongInfo)>>>,
}

impl Harness {
    fn new() -> Self {
        let temp = TempDir::new().unwrap();
        let config = ConfigManager::new(temp.path().join("config.ini")).unwrap();
        let detector = FakeDetector::new();
        let library = FakeLibrary {
            result: Arc::new(Mutex::new(true)),
            ..FakeLibrary::default()
        };
        let records = Arc::new(Mutex::new(Vec::new()));
        let callback_records = Arc::clone(&records);
        let callback: RecordCallback = Arc::new(move |record, song| {
            callback_records.lock().unwrap().push((record, song));
        });
        let monitor = MusicMonitor::new(
            Arc::new(Mutex::new(config)),
            Box::new(detector.clone()),
            Some(callback),
        );
        let library_client: Arc<dyn LibraryClient> = Arc::new(library.clone());
        monitor.set_library_client(Some(library_client));
        Self {
            _temp: temp,
            monitor,
            detector,
            library,
            records,
        }
    }

    fn history_len(&self) -> usize {
        self.monitor.play_history().len()
    }

    fn record_count(&self) -> usize {
        self.records.lock().unwrap().len()
    }
}

fn candidate(player: &str, title: &str, artist: &str, source: &str) -> PlaybackCandidate {
    PlaybackCandidate {
        song: SongInfo::new(title, artist, player),
        source: source.to_string(),
        playback_status: "playing".to_string(),
        full_title: format!("{title} - {artist}"),
    }
}

fn window_candidate(player: &str, title: &str, artist: &str) -> PlaybackCandidate {
    candidate(player, title, artist, PLAYBACK_SOURCE_WINDOW)
}

#[test]
fn monitor_poll_records_new_song() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    let history = harness.monitor.play_history();
    assert_eq!(history.len(), 1);
    assert_eq!(history[0].title, "晴天");
    assert_eq!(history[0].artist, "周杰伦");
    assert_eq!(history[0].in_library, Some(true));
    assert_eq!(harness.monitor.current_song().unwrap().title, "晴天");
    assert_eq!(
        harness.library.calls(),
        vec![("周杰伦".into(), "晴天".into())]
    );
    assert_eq!(harness.record_count(), 1);
}

#[test]
fn monitor_poll_deduplicates_same_title() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("netease", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 1);
    assert_eq!(harness.record_count(), 1);
}

#[test]
fn monitor_title_change_creates_new_record() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness
        .detector
        .set(vec![window_candidate("qq", "稻香", "周杰伦")]);
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 2);
}

#[test]
fn monitor_no_playing_clears_current_song() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.detector.set(Vec::new());
    harness.monitor.poll_once();

    assert!(harness.monitor.current_song().is_none());
    assert_eq!(harness.history_len(), 1);
}

#[test]
fn monitor_invalid_title_is_ignored() {
    let harness = Harness::new();
    harness.detector.set(Vec::new());
    harness.monitor.poll_once();
    assert!(harness.monitor.play_history().is_empty());
}

#[test]
fn monitor_play_history_is_snapshot() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    let mut snapshot = harness.monitor.play_history();
    snapshot.clear();
    assert_eq!(harness.history_len(), 1);
}

#[test]
fn monitor_clear_history() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.monitor.clear_history();
    assert!(harness.monitor.play_history().is_empty());
}

#[test]
fn monitor_start_stop() {
    let harness = Harness::new();
    let monitor = Arc::new(harness.monitor);
    monitor.start();
    assert!(monitor.is_running());
    monitor.stop();
    assert!(!monitor.is_running());
}

#[test]
fn monitor_library_failure_marks_missing() {
    let harness = Harness::new();
    harness.library.set_result(false);
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    assert_eq!(harness.monitor.play_history()[0].in_library, Some(false));
}

#[test]
fn monitor_query_error_marks_unknown() {
    let harness = Harness::new();
    harness.library.set_error(Some("服务器超时"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    let record = &harness.monitor.play_history()[0];
    assert!(record.in_library.is_none());
    assert!(record.is_unknown());
    assert!(harness.monitor.current_record().unwrap().is_unknown());
    assert!(harness.monitor.current_song().is_some());
    assert!(!harness.monitor.query_ok());
    assert!(harness
        .monitor
        .last_query_error()
        .unwrap()
        .contains("服务器超时"));
}

#[test]
fn monitor_successful_query_clears_error_state() {
    let harness = Harness::new();
    harness.library.set_error(Some("服务器超时"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    assert!(harness.monitor.last_query_error().is_some());

    harness.library.set_error(None);
    let song = harness.monitor.current_song().unwrap();
    assert_eq!(harness.monitor.recheck_song(&song), Some(true));
    assert!(harness.monitor.query_ok());
    assert!(harness.monitor.last_query_error().is_none());
}

#[test]
fn monitor_unknown_retries_without_duplicate_history() {
    let mut harness = Harness::new();
    harness.monitor.set_retry_policy(0.0, 5);
    harness.library.set_error(Some("临时超时"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    assert_eq!(harness.history_len(), 1);

    harness.library.set_error(None);
    harness.library.set_result(true);
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 1);
    assert_eq!(harness.library.calls().len(), 2);
    assert_eq!(
        harness.monitor.current_record().unwrap().in_library,
        Some(true)
    );
    assert_eq!(harness.record_count(), 2);
}

#[test]
fn monitor_unknown_retry_stops_after_max() {
    let mut harness = Harness::new();
    harness.monitor.set_retry_policy(0.0, 5);
    harness.library.set_error(Some("持续失败"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    for _ in 0..10 {
        harness.monitor.poll_once();
    }

    assert_eq!(harness.library.calls().len(), 6);
}

#[test]
fn monitor_missing_subsonic_marks_unknown() {
    let harness = Harness::new();
    harness.monitor.set_library_client(None);
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    assert!(harness.monitor.play_history()[0].in_library.is_none());
}

#[test]
fn monitor_result_cache_avoids_repeat_query() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness
        .detector
        .set(vec![window_candidate("qq", "稻香", "周杰伦")]);
    harness.monitor.poll_once();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    assert_eq!(harness.library.calls().len(), 2);
}

#[test]
fn monitor_update_current_result_only_for_current_song() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    assert!(harness
        .monitor
        .update_current_result("周杰伦", "晴天", Some(false), None));
    assert_eq!(
        harness.monitor.current_record().unwrap().in_library,
        Some(false)
    );
    assert!(!harness
        .monitor
        .update_current_result("周杰伦", "稻香", Some(true), None));
    assert_eq!(
        harness.monitor.current_record().unwrap().in_library,
        Some(false)
    );
}

#[test]
fn monitor_recheck_bypasses_cache() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.library.set_result(false);

    let song = SongInfo::new("晴天", "周杰伦", "qq");
    assert_eq!(harness.monitor.recheck_song(&song), Some(false));
    assert_eq!(harness.library.calls().len(), 2);
}

#[test]
fn monitor_reload_config_clears_cache() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.monitor.reload_config();
    let library_client: Arc<dyn LibraryClient> = Arc::new(harness.library.clone());
    harness.monitor.set_library_client(Some(library_client));

    harness
        .detector
        .set(vec![window_candidate("qq", "稻香", "周杰伦")]);
    harness.monitor.poll_once();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    assert_eq!(harness.library.calls().len(), 3);
}

#[test]
fn monitor_two_players_are_tracked_simultaneously() {
    let harness = Harness::new();
    harness.detector.set(vec![
        candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
        window_candidate("netease", "稻香", "周杰伦"),
    ]);
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 2);
    let songs = harness.monitor.current_songs();
    assert_eq!(songs.len(), 2);
    assert!(songs.contains_key("qq"));
    assert!(songs.contains_key("netease"));
    assert_eq!(songs["qq"].title, "晴天");
    assert_eq!(songs["netease"].title, "稻香");
    let sources = harness.monitor.current_sources();
    assert_eq!(sources["qq"], PLAYBACK_SOURCE_SMTC);
    assert_eq!(sources["netease"], PLAYBACK_SOURCE_WINDOW);
}

#[test]
fn monitor_same_song_on_two_players_updates_selected_player() {
    let harness = Harness::new();
    harness.detector.set(vec![
        candidate("qq", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
        candidate("netease", "晴天", "周杰伦", PLAYBACK_SOURCE_SMTC),
    ]);
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 2);
    assert_eq!(harness.library.calls().len(), 1);
    assert!(harness
        .monitor
        .update_current_result("周杰伦", "晴天", Some(false), Some("netease")));
    let records = harness.monitor.current_records();
    assert_eq!(records["qq"].in_library, Some(true));
    assert_eq!(records["netease"].in_library, Some(false));
}

#[test]
fn monitor_player_disappearing_only_clears_its_state() {
    let harness = Harness::new();
    harness.detector.set(vec![
        window_candidate("qq", "晴天", "周杰伦"),
        window_candidate("netease", "稻香", "周杰伦"),
    ]);
    harness.monitor.poll_once();

    harness
        .detector
        .set(vec![window_candidate("netease", "稻香", "周杰伦")]);
    harness.monitor.poll_once();

    let songs = harness.monitor.current_songs();
    assert_eq!(songs.keys().cloned().collect::<Vec<_>>(), ["netease"]);
    assert_eq!(harness.monitor.current_song().unwrap().player, "netease");
    assert_eq!(harness.history_len(), 2);
}

#[test]
fn monitor_same_title_is_restored_after_transient_empty_poll() {
    let harness = Harness::new();
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.detector.set(Vec::new());
    harness.monitor.poll_once();
    assert!(harness.monitor.current_song().is_none());

    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 1);
    assert_eq!(harness.monitor.current_song().unwrap().title, "晴天");
    assert!(harness.monitor.current_record().is_some());
}

#[test]
fn monitor_same_title_after_long_absence_records_new_play() {
    let mut harness = Harness::new();
    harness.monitor.set_player_reset_policy(0.0);
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.detector.set(Vec::new());
    harness.monitor.poll_once();

    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 2);
    assert_eq!(harness.monitor.current_song().unwrap().title, "晴天");
}

#[test]
fn monitor_source_switch_for_same_song_does_not_duplicate() {
    let harness = Harness::new();
    harness.detector.set(vec![candidate(
        "qq",
        "晴天",
        "周杰伦",
        PLAYBACK_SOURCE_SMTC,
    )]);
    harness.monitor.poll_once();

    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();

    assert_eq!(harness.history_len(), 1);
    assert_eq!(
        harness.monitor.current_sources()["qq"],
        PLAYBACK_SOURCE_WINDOW
    );
}

#[test]
fn monitor_unknown_retry_survives_transient_empty_poll() {
    let mut harness = Harness::new();
    harness.monitor.set_retry_policy(0.0, 5);
    harness.library.set_error(Some("临时超时"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.detector.set(Vec::new());
    harness.monitor.poll_once();

    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.library.set_error(None);
    harness.library.set_result(true);
    harness.monitor.poll_once();

    assert_eq!(
        harness.monitor.current_record().unwrap().in_library,
        Some(true)
    );
    assert_eq!(harness.history_len(), 1);
}

#[test]
fn monitor_unknown_retry_is_per_player() {
    let mut harness = Harness::new();
    harness.library.set_error(Some("临时超时"));
    harness.monitor.set_retry_policy(60.0, 5);
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    assert_eq!(harness.history_len(), 1);

    harness.monitor.set_retry_policy(0.0, 5);
    harness.detector.set(vec![
        window_candidate("qq", "晴天", "周杰伦"),
        window_candidate("netease", "稻香", "周杰伦"),
    ]);
    harness.monitor.poll_once();
    assert_eq!(harness.history_len(), 2);

    harness.library.set_error(None);
    harness.library.set_result(true);
    harness.monitor.poll_once();

    let records = harness.monitor.current_records();
    assert_eq!(records["netease"].in_library, Some(true));
    assert!(records["qq"].in_library.is_none());
}

#[test]
fn monitor_stop_is_idempotent() {
    let harness = Harness::new();
    let monitor = Arc::new(harness.monitor);
    monitor.stop();
    monitor.stop();
    assert!(!monitor.is_running());
}

#[test]
fn monitor_unknown_retry_respects_interval() {
    let mut harness = Harness::new();
    harness.monitor.set_retry_policy(60.0, 5);
    harness.library.set_error(Some("临时超时"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.monitor.poll_once();
    assert_eq!(harness.library.calls().len(), 1);
}

#[test]
fn monitor_unknown_retry_then_failure_keeps_retrying_until_max() {
    let mut harness = Harness::new();
    harness.monitor.set_retry_policy(0.0, 2);
    harness.library.set_error(Some("持续失败"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    for _ in 0..5 {
        harness.monitor.poll_once();
    }
    assert_eq!(harness.library.calls().len(), 3);
}

#[test]
fn monitor_retry_interval_does_not_block_other_players() {
    let mut harness = Harness::new();
    harness.monitor.set_retry_policy(60.0, 5);
    harness.library.set_error(Some("临时超时"));
    harness
        .detector
        .set(vec![window_candidate("qq", "晴天", "周杰伦")]);
    harness.monitor.poll_once();
    harness.monitor.set_retry_policy(0.0, 5);
    harness.detector.set(vec![
        window_candidate("qq", "晴天", "周杰伦"),
        window_candidate("netease", "稻香", "周杰伦"),
    ]);
    harness.monitor.poll_once();
    harness.library.set_error(None);
    harness.library.set_result(true);
    harness.monitor.poll_once();
    let records = harness.monitor.current_records();
    assert_eq!(records["netease"].in_library, Some(true));
    assert!(records["qq"].in_library.is_none());
}

#[test]
fn monitor_stop_timeout_path_does_not_hang() {
    let harness = Harness::new();
    let monitor = Arc::new(harness.monitor);
    monitor.start();
    std::thread::sleep(Duration::from_millis(20));
    monitor.stop();
    assert!(!monitor.is_running());
}
