//! 提醒策略（纯逻辑）。

use chrono::{DateTime, Duration, Local};

use crate::constants::{
    REMINDER_MODE_ALL, REMINDER_MODE_MISSING, REMINDER_MODE_NEW_MISSING, REMINDER_MODE_OFF,
};

pub fn should_notify(
    mode: &str,
    in_library: Option<bool>,
    is_new_missing: bool,
    last_notified_at: Option<DateTime<Local>>,
    now: DateTime<Local>,
    cooldown_minutes: i64,
) -> bool {
    if in_library.is_none() || mode == REMINDER_MODE_OFF {
        return false;
    }

    if mode == REMINDER_MODE_NEW_MISSING {
        return in_library == Some(false) && is_new_missing;
    }

    if let Some(last) = last_notified_at {
        let cooldown = Duration::minutes(cooldown_minutes.max(0));
        if now - last < cooldown {
            return false;
        }
    }

    if mode == REMINDER_MODE_MISSING {
        return in_library == Some(false);
    }
    if mode == REMINDER_MODE_ALL {
        return true;
    }

    in_library == Some(false) && is_new_missing
}
