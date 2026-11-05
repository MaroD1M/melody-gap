//! Windows 播放器窗口检测（可见窗口优先，隐藏窗口兜底）。
//!
//! 与 v1.x 不同，这里不做全进程扫描：先枚举窗口，再只反查候选窗口
//! 所属进程的可执行文件名，降低杀毒软件敏感度。

#[cfg(windows)]
use std::collections::HashMap;
#[cfg(windows)]
use std::sync::Mutex;
#[cfg(windows)]
use std::time::{Duration, Instant};

#[cfg(windows)]
use melodygap_core::constants::{
    PLAYBACK_SOURCE_WINDOW, PLAYBACK_STATUS_UNKNOWN, SUPPORTED_PLAYERS,
};
use melodygap_core::models::PlaybackCandidate;
#[cfg(windows)]
use melodygap_core::models::SongInfo;
#[cfg(windows)]
use melodygap_core::title_parser::{is_valid_song_title, parse_title, select_best_title};

#[cfg(windows)]
const PROCESS_CACHE_TTL: Duration = Duration::from_secs(10);

#[cfg(windows)]
struct ProcessCacheEntry {
    name: String,
    updated_at: Instant,
}

pub struct WindowDetector {
    #[cfg(windows)]
    process_cache: Mutex<HashMap<u32, ProcessCacheEntry>>,
}

impl WindowDetector {
    pub fn new() -> Self {
        Self {
            #[cfg(windows)]
            process_cache: Mutex::new(HashMap::new()),
        }
    }

    pub fn get_current_playings(&self, player_keys: Option<&[&str]>) -> Vec<PlaybackCandidate> {
        #[cfg(not(windows))]
        {
            let _ = player_keys;
            Vec::new()
        }

        #[cfg(windows)]
        {
            self.get_current_playings_windows(player_keys)
        }
    }

    #[cfg(windows)]
    fn get_current_playings_windows(&self, player_keys: Option<&[&str]>) -> Vec<PlaybackCandidate> {
        let windows = enumerate_windows();
        let mut visible: HashMap<&'static str, Vec<String>> = HashMap::new();
        let mut hidden: HashMap<&'static str, Vec<String>> = HashMap::new();

        for window in windows {
            let Some(process_name) = self.process_name(window.pid) else {
                continue;
            };
            let Some(player) = SUPPORTED_PLAYERS.iter().find(|player| {
                player
                    .processes
                    .iter()
                    .any(|name| name.eq_ignore_ascii_case(&process_name))
            }) else {
                continue;
            };
            if !is_valid_song_title(&window.title, player.key) {
                continue;
            }
            let bucket = if window.visible {
                &mut visible
            } else {
                &mut hidden
            };
            bucket.entry(player.key).or_default().push(window.title);
        }

        let keys: Vec<&str> = match player_keys {
            Some(keys) => keys.to_vec(),
            None => SUPPORTED_PLAYERS.iter().map(|player| player.key).collect(),
        };

        let mut result = Vec::new();
        for key in keys {
            let titles = visible
                .get(key)
                .filter(|items| !items.is_empty())
                .or_else(|| hidden.get(key).filter(|items| !items.is_empty()));
            let Some(titles) = titles else {
                continue;
            };
            let parsed: Vec<(String, SongInfo)> = titles
                .iter()
                .filter_map(|title| parse_title(title, key).map(|song| (title.clone(), song)))
                .collect();
            if parsed.is_empty() {
                continue;
            }
            let all_titles: Vec<String> = parsed.iter().map(|(title, _)| title.clone()).collect();
            let Some(best_title) = select_best_title(&all_titles) else {
                continue;
            };
            let Some((_, song)) = parsed.into_iter().find(|(title, _)| *title == best_title) else {
                continue;
            };
            result.push(PlaybackCandidate {
                song,
                source: PLAYBACK_SOURCE_WINDOW.to_string(),
                playback_status: PLAYBACK_STATUS_UNKNOWN.to_string(),
                full_title: best_title,
            });
        }
        result
    }

    #[cfg(windows)]
    fn process_name(&self, pid: u32) -> Option<String> {
        if let Ok(cache) = self.process_cache.lock() {
            if let Some(entry) = cache.get(&pid) {
                if entry.updated_at.elapsed() < PROCESS_CACHE_TTL {
                    return Some(entry.name.clone());
                }
            }
        }

        let name = query_process_name(pid)?;
        if let Ok(mut cache) = self.process_cache.lock() {
            cache.insert(
                pid,
                ProcessCacheEntry {
                    name: name.clone(),
                    updated_at: Instant::now(),
                },
            );
        }
        Some(name)
    }
}

impl Default for WindowDetector {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(windows)]
struct RawWindow {
    title: String,
    pid: u32,
    visible: bool,
}

#[cfg(windows)]
fn enumerate_windows() -> Vec<RawWindow> {
    use windows::core::BOOL;
    use windows::Win32::Foundation::{HWND, LPARAM};
    use windows::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetWindowTextLengthW, GetWindowTextW, GetWindowThreadProcessId,
        IsWindowVisible,
    };

    struct Context {
        windows: Vec<RawWindow>,
    }

    unsafe extern "system" fn callback(hwnd: HWND, lparam: LPARAM) -> BOOL {
        let context = &mut *(lparam.0 as *mut Context);
        let length = GetWindowTextLengthW(hwnd);
        if length <= 0 {
            return BOOL(1);
        }
        let mut buffer = vec![0u16; length as usize + 1];
        let copied = GetWindowTextW(hwnd, &mut buffer);
        if copied <= 0 {
            return BOOL(1);
        }
        let title = String::from_utf16_lossy(&buffer[..copied as usize]);
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if pid != 0 && !title.trim().is_empty() {
            context.windows.push(RawWindow {
                title,
                pid,
                visible: IsWindowVisible(hwnd).as_bool(),
            });
        }
        BOOL(1)
    }

    let mut context = Context {
        windows: Vec::new(),
    };
    unsafe {
        let _ = EnumWindows(
            Some(callback),
            LPARAM(&mut context as *mut Context as isize),
        );
    }
    context.windows
}

#[cfg(windows)]
fn query_process_name(pid: u32) -> Option<String> {
    use windows::core::PWSTR;
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{
        OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
        PROCESS_QUERY_LIMITED_INFORMATION,
    };

    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let mut buffer = vec![0u16; 1024];
        let mut size = buffer.len() as u32;
        let result = QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(buffer.as_mut_ptr()),
            &mut size,
        );
        let _ = CloseHandle(handle);
        result.ok()?;
        let path = String::from_utf16_lossy(&buffer[..size as usize]);
        let name = path
            .rsplit(['\\', '/'])
            .next()
            .unwrap_or(path.as_str())
            .to_lowercase();
        if name.is_empty() {
            None
        } else {
            Some(name)
        }
    }
}
