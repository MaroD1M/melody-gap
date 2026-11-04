//! Windows SMTC（系统媒体会话）播放检测。
//!
//! 后台线程每 2 秒刷新一次快照；监控线程只读取快照，WinRT 对象不跨线程。
//! 非 Windows 平台返回空快照，窗口检测仍可正常工作。

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
#[cfg(windows)]
use std::thread;
use std::thread::JoinHandle;
#[cfg(windows)]
use std::time::Duration;

#[cfg(windows)]
use melodygap_core::constants::SMTC_POLL_INTERVAL_SECONDS;
use melodygap_core::models::PlaybackCandidate;

#[derive(Debug, Clone, Default)]
pub struct SmtcState {
    pub available: bool,
    pub last_error: Option<String>,
}

pub struct SmtcDetector {
    snapshot: Arc<Mutex<Vec<PlaybackCandidate>>>,
    state: Arc<Mutex<SmtcState>>,
    stop: Arc<AtomicBool>,
    thread: Mutex<Option<JoinHandle<()>>>,
}

impl SmtcDetector {
    pub fn new() -> Self {
        Self {
            snapshot: Arc::new(Mutex::new(Vec::new())),
            state: Arc::new(Mutex::new(SmtcState::default())),
            stop: Arc::new(AtomicBool::new(false)),
            thread: Mutex::new(None),
        }
    }

    pub fn start(&self) -> bool {
        #[cfg(not(windows))]
        {
            false
        }

        #[cfg(windows)]
        {
            let mut guard = self.thread.lock().expect("smtc thread lock");
            if guard.is_some() {
                return self.state.lock().expect("smtc state").available;
            }
            self.stop.store(false, Ordering::SeqCst);
            let snapshot = Arc::clone(&self.snapshot);
            let state = Arc::clone(&self.state);
            let stop = Arc::clone(&self.stop);
            *guard = Some(
                thread::Builder::new()
                    .name("SmtcDetector".into())
                    .spawn(move || smtc_loop(snapshot, state, stop))
                    .expect("spawn smtc thread"),
            );
            true
        }
    }

    pub fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
        let handle = self.thread.lock().expect("smtc thread lock").take();
        if let Some(handle) = handle {
            let _ = handle.join();
        }
        self.snapshot.lock().expect("smtc snapshot").clear();
        let mut state = self.state.lock().expect("smtc state");
        state.available = false;
    }

    pub fn snapshot(&self) -> Vec<PlaybackCandidate> {
        self.snapshot.lock().expect("smtc snapshot").clone()
    }

    pub fn available(&self) -> bool {
        self.state.lock().expect("smtc state").available
    }

    pub fn last_error(&self) -> Option<String> {
        self.state.lock().expect("smtc state").last_error.clone()
    }
}

impl Default for SmtcDetector {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(windows)]
fn smtc_loop(
    snapshot: Arc<Mutex<Vec<PlaybackCandidate>>>,
    state: Arc<Mutex<SmtcState>>,
    stop: Arc<AtomicBool>,
) {
    use windows::Media::Control::GlobalSystemMediaTransportControlsSessionManager;
    use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};

    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
    }

    let mut manager = None;
    while !stop.load(Ordering::SeqCst) && manager.is_none() {
        match wait_operation(
            GlobalSystemMediaTransportControlsSessionManager::RequestAsync(),
            Duration::from_secs(3),
        ) {
            Ok(value) => manager = Some(value),
            Err(error) => {
                let mut guard = state.lock().expect("smtc state");
                guard.last_error = Some(format!("获取 SMTC 管理器失败: {error}"));
                drop(guard);
                sleep_or_stop(&stop, Duration::from_secs(5));
            }
        }
    }

    let Some(manager) = manager else {
        return;
    };

    {
        let mut guard = state.lock().expect("smtc state");
        guard.available = true;
        guard.last_error = None;
    }

    while !stop.load(Ordering::SeqCst) {
        match read_sessions(&manager, &stop) {
            Ok(candidates) => {
                *snapshot.lock().expect("smtc snapshot") = candidates;
                let mut guard = state.lock().expect("smtc state");
                guard.available = true;
                guard.last_error = None;
            }
            Err(error) => {
                snapshot.lock().expect("smtc snapshot").clear();
                let mut guard = state.lock().expect("smtc state");
                guard.last_error = Some(format!("读取 SMTC 会话失败: {error}"));
            }
        }
        sleep_or_stop(&stop, Duration::from_secs_f64(SMTC_POLL_INTERVAL_SECONDS));
    }

    let mut guard = state.lock().expect("smtc state");
    guard.available = false;
}

#[cfg(windows)]
fn wait_operation<T>(
    operation: windows::core::Result<windows_future::IAsyncOperation<T>>,
    timeout: Duration,
) -> Result<T, String>
where
    T: windows::core::RuntimeType + 'static,
{
    use std::time::Instant;

    use windows_future::AsyncStatus;

    let operation = operation.map_err(|error| error.to_string())?;
    let started = Instant::now();
    loop {
        let status = operation.Status().map_err(|error| error.to_string())?;
        if status != AsyncStatus::Started {
            return operation.GetResults().map_err(|error| error.to_string());
        }
        if started.elapsed() >= timeout {
            let _ = operation.Cancel();
            return Err("SMTC 请求超时".to_string());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

#[cfg(windows)]
fn read_sessions(
    manager: &windows::Media::Control::GlobalSystemMediaTransportControlsSessionManager,
    stop: &AtomicBool,
) -> Result<Vec<PlaybackCandidate>, String> {
    use std::collections::HashMap;

    use melodygap_core::constants::{
        PLAYBACK_SOURCE_SMTC, PLAYBACK_STATUS_PAUSED, PLAYBACK_STATUS_PLAYING,
        PLAYBACK_STATUS_STOPPED, PLAYBACK_STATUS_UNKNOWN, SUPPORTED_PLAYERS,
    };
    use melodygap_core::title_parser::parse_title;

    let sessions = manager.GetSessions().map_err(|error| error.to_string())?;
    let mut best: HashMap<&'static str, (i32, PlaybackCandidate)> = HashMap::new();

    for session in &sessions {
        if stop.load(Ordering::SeqCst) {
            break;
        }
        let app_id = session
            .SourceAppUserModelId()
            .map(|value| value.to_string())
            .unwrap_or_default();
        let Some(player) = melodygap_core::constants::match_player_by_app_id(&app_id) else {
            continue;
        };

        let properties = match wait_operation(
            session.TryGetMediaPropertiesAsync(),
            Duration::from_millis(2500),
        ) {
            Ok(value) => value,
            Err(_) => continue,
        };
        let mut title = properties
            .Title()
            .map(|value| value.to_string())
            .unwrap_or_default()
            .trim()
            .to_string();
        let mut artist = properties
            .Artist()
            .map(|value| value.to_string())
            .unwrap_or_default()
            .trim()
            .to_string();
        if title.is_empty() {
            continue;
        }
        if artist.is_empty() {
            if let Some(parsed) = parse_title(&title, player) {
                title = parsed.title;
                artist = parsed.artist;
            }
        }

        let status = session
            .GetPlaybackInfo()
            .ok()
            .and_then(|info| info.PlaybackStatus().ok())
            .map(|status| melodygap_core::constants::playback_status_from_code(status.0))
            .unwrap_or(PLAYBACK_STATUS_UNKNOWN);
        let priority = match status {
            PLAYBACK_STATUS_PLAYING => 3,
            PLAYBACK_STATUS_PAUSED => 2,
            PLAYBACK_STATUS_STOPPED => 1,
            _ => 0,
        };
        let full_title = format!("{title} - {artist}")
            .trim_matches(|c| c == ' ' || c == '-')
            .to_string();
        let candidate = PlaybackCandidate {
            song: melodygap_core::models::SongInfo::new(title, artist, player),
            source: PLAYBACK_SOURCE_SMTC.to_string(),
            playback_status: status.to_string(),
            full_title,
        };
        match best.get(player) {
            Some((existing, _)) if *existing >= priority => {}
            _ => {
                best.insert(player, (priority, candidate));
            }
        }
    }

    let mut result = Vec::new();
    for player in SUPPORTED_PLAYERS {
        if let Some((_, candidate)) = best.remove(player.key) {
            result.push(candidate);
        }
    }
    Ok(result)
}

#[cfg(windows)]
fn sleep_or_stop(stop: &AtomicBool, duration: Duration) {
    let step = Duration::from_millis(100);
    let mut elapsed = Duration::ZERO;
    while elapsed < duration {
        if stop.load(Ordering::SeqCst) {
            return;
        }
        let sleep = step.min(duration - elapsed);
        thread::sleep(sleep);
        elapsed += sleep;
    }
}
