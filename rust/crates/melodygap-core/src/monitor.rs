//! 播放监控核心：轮询检测、曲库查询、双播放器状态与历史记录。

use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crate::config::ConfigManager;
use crate::constants::{
    player_config, player_display_name, MONITOR_INTERVAL_SECONDS, MONITOR_STOP_TIMEOUT_SECONDS,
    PLAYBACK_SOURCE_SMTC, PLAYBACK_SOURCE_WINDOW, PLAYBACK_STATUS_PLAYING, PLAYBACK_STATUS_UNKNOWN,
    PLAYER_STATE_RESET_SECONDS, SUPPORTED_PLAYERS, UNKNOWN_RETRY_MAX, UNKNOWN_RETRY_SECONDS,
};
use crate::matcher::SongMatcher;
use crate::models::{PlayRecord, PlaybackCandidate, SongInfo};
use crate::subsonic::{LibraryClient, SubsonicClient, SubsonicError};
use crate::title_parser::parse_title;

pub type RecordCallback = Arc<dyn Fn(PlayRecord, SongInfo) + Send + Sync>;

pub trait PlaybackDetector: Send {
    fn start(&mut self) {}
    fn stop(&mut self) {}
    fn get_current_playings(&mut self) -> Vec<PlaybackCandidate>;
}

#[derive(Clone, Debug, Default)]
struct UnknownRetry {
    count: u32,
    next_at: Option<Instant>,
}

#[derive(Default)]
struct MonitorState {
    current_songs: BTreeMap<String, SongInfo>,
    current_records: BTreeMap<String, PlayRecord>,
    current_sources: BTreeMap<String, String>,
    last_keys: BTreeMap<String, (String, String)>,
    last_records: BTreeMap<String, PlayRecord>,
    missing_since: BTreeMap<String, Instant>,
    unknown_retries: BTreeMap<String, UnknownRetry>,
    last_query_error: Option<String>,
    query_ok: bool,
}

pub struct MusicMonitor {
    config: Arc<Mutex<ConfigManager>>,
    detector: Mutex<Box<dyn PlaybackDetector>>,
    library: Mutex<Option<Arc<dyn LibraryClient>>>,
    on_record: Mutex<Option<RecordCallback>>,
    history: Mutex<Vec<PlayRecord>>,
    state: Mutex<MonitorState>,
    cache: Mutex<HashMap<(String, String), bool>>,
    running: AtomicBool,
    stop_tx: Mutex<Option<mpsc::Sender<()>>>,
    thread: Mutex<Option<JoinHandle<()>>>,
    retry_interval: f64,
    retry_max: u32,
    player_reset_seconds: f64,
}

impl MusicMonitor {
    pub fn new(
        config: Arc<Mutex<ConfigManager>>,
        detector: Box<dyn PlaybackDetector>,
        on_record: Option<RecordCallback>,
    ) -> Self {
        let monitor = Self {
            config,
            detector: Mutex::new(detector),
            library: Mutex::new(None),
            on_record: Mutex::new(on_record),
            history: Mutex::new(Vec::new()),
            state: Mutex::new(MonitorState::default()),
            cache: Mutex::new(HashMap::new()),
            running: AtomicBool::new(false),
            stop_tx: Mutex::new(None),
            thread: Mutex::new(None),
            retry_interval: UNKNOWN_RETRY_SECONDS,
            retry_max: UNKNOWN_RETRY_MAX,
            player_reset_seconds: PLAYER_STATE_RESET_SECONDS,
        };
        monitor.setup_library();
        monitor
    }

    pub fn set_library_client(&self, client: Option<Arc<dyn LibraryClient>>) {
        *self.library.lock().expect("library lock") = client;
    }

    pub fn set_on_record(&self, callback: Option<RecordCallback>) {
        *self.on_record.lock().expect("callback lock") = callback;
    }

    pub fn set_retry_policy(&mut self, interval_seconds: f64, max_retries: u32) {
        self.retry_interval = interval_seconds;
        self.retry_max = max_retries;
    }

    pub fn set_player_reset_policy(&mut self, seconds: f64) {
        self.player_reset_seconds = seconds;
    }

    fn setup_library(&self) {
        let config = self.config.lock().expect("config lock");
        if !config.is_subsonic_configured() {
            tracing::warn!("Subsonic 配置不完整，请在设置中填写服务器信息");
            self.set_library_client(None);
            return;
        }
        let subsonic = config.get_subsonic_config();
        drop(config);

        match SubsonicClient::with_defaults(
            &subsonic.server_url,
            &subsonic.username,
            &subsonic.password,
            subsonic.verify_ssl,
        ) {
            Ok(client) => {
                tracing::info!(server = %subsonic.server_url, "Subsonic 客户端已初始化");
                self.set_library_client(Some(Arc::new(client)));
            }
            Err(error) => {
                tracing::error!(%error, "初始化 Subsonic 客户端失败");
                self.set_library_client(None);
            }
        }
    }

    pub fn reload_config(&self) {
        self.setup_library();
        {
            let mut state = self.state.lock().expect("state lock");
            state.last_keys.clear();
            state.last_query_error = None;
            state.query_ok = false;
            state.unknown_retries.clear();
        }
        self.cache.lock().expect("cache lock").clear();
    }

    pub fn play_history(&self) -> Vec<PlayRecord> {
        self.history.lock().expect("history lock").clone()
    }

    pub fn clear_history(&self) {
        self.history.lock().expect("history lock").clear();
        tracing::info!("播放历史已清空");
    }

    pub fn last_query_error(&self) -> Option<String> {
        self.state
            .lock()
            .expect("state lock")
            .last_query_error
            .clone()
    }

    pub fn query_ok(&self) -> bool {
        self.state.lock().expect("state lock").query_ok
    }

    fn set_query_state(&self, ok: bool, error: Option<String>) {
        let mut state = self.state.lock().expect("state lock");
        state.query_ok = ok;
        state.last_query_error = error;
    }

    fn ordered_players<'a>(players: impl Iterator<Item = &'a String>) -> Vec<String> {
        let order: Vec<&str> = SUPPORTED_PLAYERS.iter().map(|item| item.key).collect();
        let mut values: Vec<String> = players.cloned().collect();
        values.sort_by_key(|key| {
            (
                order
                    .iter()
                    .position(|item| item == key)
                    .unwrap_or(order.len()),
                key.clone(),
            )
        });
        values
    }

    pub fn current_songs(&self) -> BTreeMap<String, SongInfo> {
        let state = self.state.lock().expect("state lock");
        Self::ordered_players(state.current_songs.keys())
            .into_iter()
            .filter_map(|key| {
                state
                    .current_songs
                    .get(&key)
                    .cloned()
                    .map(|song| (key, song))
            })
            .collect()
    }

    pub fn current_records(&self) -> BTreeMap<String, PlayRecord> {
        let state = self.state.lock().expect("state lock");
        Self::ordered_players(state.current_records.keys())
            .into_iter()
            .filter_map(|key| {
                state
                    .current_records
                    .get(&key)
                    .cloned()
                    .map(|record| (key, record))
            })
            .collect()
    }

    pub fn current_sources(&self) -> BTreeMap<String, String> {
        let state = self.state.lock().expect("state lock");
        Self::ordered_players(state.current_sources.keys())
            .into_iter()
            .map(|key| {
                (
                    key.clone(),
                    state
                        .current_sources
                        .get(&key)
                        .cloned()
                        .unwrap_or_else(|| PLAYBACK_SOURCE_WINDOW.to_string()),
                )
            })
            .collect()
    }

    pub fn current_song(&self) -> Option<SongInfo> {
        let state = self.state.lock().expect("state lock");
        Self::ordered_players(state.current_songs.keys())
            .into_iter()
            .find_map(|key| state.current_songs.get(&key).cloned())
    }

    pub fn current_record(&self) -> Option<PlayRecord> {
        let state = self.state.lock().expect("state lock");
        Self::ordered_players(state.current_songs.keys())
            .into_iter()
            .find_map(|key| state.current_records.get(&key).cloned())
    }

    pub fn update_current_result(
        &self,
        artist: &str,
        title: &str,
        in_library: Option<bool>,
        player: Option<&str>,
    ) -> bool {
        let mut state = self.state.lock().expect("state lock");
        let players: Vec<String> = match player {
            Some(key) => vec![key.to_string()],
            None => Self::ordered_players(state.current_songs.keys()),
        };
        let mut updated = false;
        for key in players {
            let Some(song) = state.current_songs.get(&key) else {
                continue;
            };
            if song.artist != artist || song.title != title {
                continue;
            }
            if let Some(record) = state.current_records.get_mut(&key) {
                record.in_library = in_library;
                updated = true;
            }
        }
        updated
    }

    fn check_library(&self, song: &SongInfo) -> Option<bool> {
        let library = self.library.lock().expect("library lock").clone();
        let Some(library) = library else {
            self.set_query_state(false, Some("服务器尚未配置".to_string()));
            return None;
        };

        let cache_key = (song.artist.clone(), song.title.clone());
        if let Some(cached) = self
            .cache
            .lock()
            .expect("cache lock")
            .get(&cache_key)
            .copied()
        {
            tracing::debug!(song = %song.display_text(), "曲库缓存命中");
            self.set_query_state(true, None);
            return Some(cached);
        }

        match library.find_exact_match(&song.artist, &song.title) {
            Ok(result) => {
                self.cache
                    .lock()
                    .expect("cache lock")
                    .insert(cache_key, result);
                self.set_query_state(true, None);
                Some(result)
            }
            Err(error) => {
                tracing::warn!(%error, "曲库查询失败");
                self.set_query_state(false, Some(error.to_string()));
                None
            }
        }
    }

    pub fn recheck_song(&self, song: &SongInfo) -> Option<bool> {
        let library = self.library.lock().expect("library lock").clone();
        let Some(library) = library else {
            self.set_query_state(false, Some("服务器尚未配置".to_string()));
            return None;
        };
        match library.find_exact_match(&song.artist, &song.title) {
            Ok(result) => {
                self.cache
                    .lock()
                    .expect("cache lock")
                    .insert((song.artist.clone(), song.title.clone()), result);
                self.set_query_state(true, None);
                Some(result)
            }
            Err(error) => {
                tracing::warn!(%error, "核验失败");
                self.set_query_state(false, Some(error.to_string()));
                None
            }
        }
    }

    fn detect_candidates(&self) -> Vec<PlaybackCandidate> {
        let mut detector = self.detector.lock().expect("detector lock");
        detector.get_current_playings()
    }

    fn select_candidates(
        candidates: Vec<PlaybackCandidate>,
    ) -> BTreeMap<String, PlaybackCandidate> {
        let mut selected: BTreeMap<String, PlaybackCandidate> = BTreeMap::new();
        for candidate in candidates {
            if candidate.title().is_empty() || candidate.player().is_empty() {
                continue;
            }
            match selected.get(candidate.player()) {
                None => {
                    selected.insert(candidate.player().to_string(), candidate);
                }
                Some(previous) => {
                    let score = (
                        candidate.playback_status == PLAYBACK_STATUS_PLAYING,
                        candidate.source == PLAYBACK_SOURCE_SMTC,
                    );
                    let previous_score = (
                        previous.playback_status == PLAYBACK_STATUS_PLAYING,
                        previous.source == PLAYBACK_SOURCE_SMTC,
                    );
                    if score > previous_score {
                        selected.insert(candidate.player().to_string(), candidate);
                    }
                }
            }
        }
        selected
    }

    fn clear_inactive_players(&self, active: &HashSet<String>) {
        let now = Instant::now();
        let mut state = self.state.lock().expect("state lock");

        for player in active {
            state.missing_since.remove(player);
        }

        let mut tracked: HashSet<String> = state.current_songs.keys().cloned().collect();
        tracked.extend(state.last_keys.keys().cloned());
        for player in tracked.difference(active) {
            state.current_songs.remove(player);
            state.current_records.remove(player);
            state.current_sources.remove(player);
            let missing_since = *state.missing_since.entry(player.clone()).or_insert(now);
            if now.duration_since(missing_since).as_secs_f64() >= self.player_reset_seconds {
                state.last_keys.remove(player);
                state.last_records.remove(player);
                state.unknown_retries.remove(player);
            }
        }
    }

    pub fn poll_once(&self) {
        let candidates = Self::select_candidates(self.detect_candidates());
        if candidates.is_empty() {
            self.clear_inactive_players(&HashSet::new());
            return;
        }

        for (player, candidate) in &candidates {
            self.process_candidate(player, candidate);
        }
        let active: HashSet<String> = candidates.keys().cloned().collect();
        self.clear_inactive_players(&active);
    }

    fn process_candidate(&self, player: &str, candidate: &PlaybackCandidate) {
        let song = &candidate.song;
        let song_key = (song.artist.clone(), song.title.clone());
        let full_title = if candidate.full_title.is_empty() {
            format!("{} - {}", song.title, song.artist)
        } else {
            candidate.full_title.clone()
        };

        let is_same = {
            let state = self.state.lock().expect("state lock");
            state.last_keys.get(player) == Some(&song_key)
        };
        if is_same {
            let mut state = self.state.lock().expect("state lock");
            state.current_songs.insert(player.to_string(), song.clone());
            state
                .current_sources
                .insert(player.to_string(), candidate.source.clone());
            if !state.current_records.contains_key(player) {
                if let Some(previous) = state.last_records.get(player).cloned() {
                    state.current_records.insert(player.to_string(), previous);
                }
            }
            drop(state);
            self.retry_unknown_if_due(player);
            return;
        }

        {
            let mut state = self.state.lock().expect("state lock");
            state.current_songs.insert(player.to_string(), song.clone());
            state.current_records.remove(player);
            state
                .current_sources
                .insert(player.to_string(), candidate.source.clone());
            state.unknown_retries.remove(player);
        }

        let in_library = self.check_library(song);
        let record = PlayRecord::create(song, in_library, &full_title);

        {
            let mut history = self.history.lock().expect("history lock");
            history.push(record.clone());
        }
        {
            let mut state = self.state.lock().expect("state lock");
            state.current_songs.insert(player.to_string(), song.clone());
            state
                .current_records
                .insert(player.to_string(), record.clone());
            state
                .current_sources
                .insert(player.to_string(), candidate.source.clone());
            state
                .last_records
                .insert(player.to_string(), record.clone());
            state.last_keys.insert(player.to_string(), song_key);
        }

        if in_library.is_none() {
            self.schedule_unknown_retry(player);
        }

        tracing::info!(
            player = %player_display_name(player),
            song = %song.display_text(),
            status = record.status_text(),
            "检测到新歌曲"
        );
        self.emit_record(&record, song);
    }

    fn schedule_unknown_retry(&self, player: &str) {
        let mut state = self.state.lock().expect("state lock");
        state.unknown_retries.insert(
            player.to_string(),
            UnknownRetry {
                count: 0,
                next_at: Some(Instant::now() + Duration::from_secs_f64(self.retry_interval)),
            },
        );
    }

    fn retry_unknown_if_due(&self, player: &str) {
        let (song, record) = {
            let state = self.state.lock().expect("state lock");
            let Some(retry) = state.unknown_retries.get(player) else {
                return;
            };
            if retry.count >= self.retry_max {
                return;
            }
            if retry.next_at.is_some_and(|next| Instant::now() < next) {
                return;
            }
            let Some(record) = state.current_records.get(player).cloned() else {
                return;
            };
            let Some(song) = state.current_songs.get(player).cloned() else {
                return;
            };
            if record.in_library.is_some() {
                return;
            }
            drop(state);
            let mut state = self.state.lock().expect("state lock");
            if let Some(retry) = state.unknown_retries.get_mut(player) {
                retry.count += 1;
                retry.next_at = Some(Instant::now() + Duration::from_secs_f64(self.retry_interval));
            }
            (song, record)
        };

        tracing::info!(
            player,
            song = %song.display_text(),
            "重试曲库查询"
        );
        let Some(result) = self.check_library(&song) else {
            return;
        };

        {
            let mut state = self.state.lock().expect("state lock");
            let Some(current) = state.current_records.get_mut(player) else {
                return;
            };
            if current.timestamp != record.timestamp || current.title != record.title {
                return;
            }
            current.in_library = Some(result);
            state.unknown_retries.remove(player);
        }

        let mut updated = record;
        updated.in_library = Some(result);
        self.emit_record(&updated, &song);
    }

    fn emit_record(&self, record: &PlayRecord, song: &SongInfo) {
        let callback = self.on_record.lock().expect("callback lock").clone();
        if let Some(callback) = callback {
            if let Err(error) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                callback(record.clone(), song.clone());
            })) {
                tracing::error!(?error, "记录回调执行失败");
            }
        }
    }

    pub fn start(self: &Arc<Self>) {
        if self.running.swap(true, Ordering::SeqCst) {
            return;
        }
        {
            let mut detector = self.detector.lock().expect("detector lock");
            detector.start();
        }
        let (tx, rx) = mpsc::channel::<()>();
        *self.stop_tx.lock().expect("stop lock") = Some(tx);
        let monitor = Arc::clone(self);
        let handle = thread::Builder::new()
            .name("MusicMonitor".to_string())
            .spawn(move || monitor.run_loop(rx))
            .expect("spawn monitor thread");
        *self.thread.lock().expect("thread lock") = Some(handle);
        tracing::info!("监控线程已启动");
    }

    fn run_loop(&self, rx: mpsc::Receiver<()>) {
        let interval = Duration::from_secs_f64(MONITOR_INTERVAL_SECONDS);
        while self.running.load(Ordering::SeqCst) {
            self.poll_once();
            match rx.recv_timeout(interval) {
                Ok(()) | Err(RecvTimeoutError::Disconnected) => break,
                Err(RecvTimeoutError::Timeout) => {}
            }
        }
        tracing::info!("监控线程已停止");
    }

    pub fn stop(&self) {
        if !self.running.swap(false, Ordering::SeqCst) {
            return;
        }
        if let Some(tx) = self.stop_tx.lock().expect("stop lock").take() {
            let _ = tx.send(());
        }
        if let Some(handle) = self.thread.lock().expect("thread lock").take() {
            let timeout = Duration::from_secs_f64(MONITOR_STOP_TIMEOUT_SECONDS);
            let start = Instant::now();
            while !handle.is_finished() && start.elapsed() < timeout {
                thread::sleep(Duration::from_millis(20));
            }
            if handle.is_finished() {
                let _ = handle.join();
            } else {
                tracing::warn!("监控线程未在超时时间内退出");
            }
        }
        {
            let mut detector = self.detector.lock().expect("detector lock");
            detector.stop();
        }
        tracing::info!("监控已停止");
    }

    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }
}

/// 兼容旧的单播放器检测器接口。
pub fn candidate_from_title(player: &str, full_title: &str) -> Option<PlaybackCandidate> {
    let song = parse_title(full_title, player)?;
    Some(PlaybackCandidate {
        song,
        source: PLAYBACK_SOURCE_WINDOW.to_string(),
        playback_status: PLAYBACK_STATUS_UNKNOWN.to_string(),
        full_title: full_title.to_string(),
    })
}

/// 供测试/外部构造默认匹配器。
pub fn default_matcher() -> SongMatcher {
    SongMatcher::default()
}

/// 方便日志中展示播放器配置。
pub fn player_exists(key: &str) -> bool {
    player_config(key).is_some()
}

impl From<SubsonicError> for String {
    fn from(value: SubsonicError) -> Self {
        value.to_string()
    }
}
