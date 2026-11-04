//! 歌曲状态通知窗（右下角、6 秒自动关闭、最多排队 5 条）。

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde::Serialize;
use tauri::{
    AppHandle, Emitter, PhysicalPosition, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};

const QUEUE_MAX: usize = 5;
const WIDTH: f64 = 420.0;
const HEIGHT: f64 = 150.0;
const MARGIN_RIGHT: f64 = 30.0;
const MARGIN_BOTTOM: f64 = 80.0;
const DURATION: Duration = Duration::from_secs(6);

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct NotificationItem {
    pub id: u64,
    pub title: String,
    pub artist: String,
    pub status: Option<bool>,
    pub player: String,
    pub player_name: String,
    pub is_new_missing: bool,
    pub copy_text: String,
}

impl NotificationItem {
    fn same_content(&self, other: &Self) -> bool {
        self.title == other.title
            && self.artist == other.artist
            && self.status == other.status
            && self.player == other.player
            && self.is_new_missing == other.is_new_missing
            && self.copy_text == other.copy_text
    }
}

pub struct NotificationManager {
    app: AppHandle,
    window: Option<WebviewWindow>,
    queue: Mutex<VecDeque<NotificationItem>>,
    current: Mutex<Option<NotificationItem>>,
    next_id: AtomicU64,
}

impl NotificationManager {
    pub fn new(app: AppHandle) -> Arc<Self> {
        let window = WebviewWindowBuilder::new(
            &app,
            "notification",
            WebviewUrl::App("index.html?window=notification".into()),
        )
        .title("MelodyGap 通知")
        .inner_size(WIDTH, HEIGHT)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .focused(false)
        .visible(false)
        .shadow(true)
        .build()
        .ok();

        Arc::new(Self {
            app,
            window,
            queue: Mutex::new(VecDeque::new()),
            current: Mutex::new(None),
            next_id: AtomicU64::new(1),
        })
    }

    pub fn push(self: &Arc<Self>, mut item: NotificationItem) {
        item.id = self.next_id.fetch_add(1, Ordering::SeqCst);
        {
            let current = self.current.lock().expect("notification current");
            if let Some(current) = current.as_ref() {
                if current.same_content(&item) {
                    return;
                }
            }
            let mut queue = self.queue.lock().expect("notification queue");
            if queue.iter().any(|queued| queued.same_content(&item)) {
                return;
            }
            if queue.len() >= QUEUE_MAX {
                tracing::debug!(title = %item.title, "通知队列已满，忽略");
                return;
            }
            queue.push_back(item);
        }
        self.advance();
    }

    fn advance(self: &Arc<Self>) {
        let next = {
            let mut current = self.current.lock().expect("notification current");
            if current.is_some() {
                return;
            }
            let item = self.queue.lock().expect("notification queue").pop_front();
            *current = item.clone();
            item
        };
        let Some(item) = next else {
            if let Some(window) = &self.window {
                let _ = window.hide();
            }
            return;
        };

        if let Some(window) = &self.window {
            self.position_window(window);
            let _ = window.show();
            let _ = window.set_always_on_top(true);
            let _ = self
                .app
                .emit_to("notification", "notification", item.clone());
        } else {
            let _ = self.app.emit("notification-fallback", item.clone());
        }

        let manager = Arc::clone(self);
        thread::Builder::new()
            .name("NotificationTimer".into())
            .spawn(move || {
                thread::sleep(DURATION);
                manager.dismiss_if(item.id);
            })
            .ok();
    }

    pub fn current(&self) -> Option<NotificationItem> {
        self.current.lock().expect("notification current").clone()
    }

    pub fn dismiss(self: &Arc<Self>) {
        let current = self.current.lock().expect("notification current").take();
        if let Some(item) = current {
            self.dismiss_if(item.id);
        }
    }

    pub fn dismiss_if(self: &Arc<Self>, id: u64) {
        {
            let mut current = self.current.lock().expect("notification current");
            if current.as_ref().is_none_or(|item| item.id != id) {
                return;
            }
            *current = None;
        }
        if let Some(window) = &self.window {
            let _ = window.hide();
        }
        self.advance();
    }

    fn position_window(&self, window: &WebviewWindow) {
        let Ok(Some(monitor)) = self.app.primary_monitor() else {
            return;
        };
        let scale = monitor.scale_factor();
        let size = monitor.size();
        let origin = monitor.position();
        let width = (WIDTH * scale) as i32;
        let height = (HEIGHT * scale) as i32;
        let right = (MARGIN_RIGHT * scale) as i32;
        let bottom = (MARGIN_BOTTOM * scale) as i32;
        let x = origin.x + size.width as i32 - width - right;
        let y = origin.y + size.height as i32 - height - bottom;
        let _ = window.set_position(PhysicalPosition::new(x, y));
    }
}
