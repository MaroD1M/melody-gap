//! 播放器窗口标题解析（纯函数）。

use std::sync::OnceLock;

use regex::Regex;

use crate::constants::{
    EXCLUDED_TITLE_KEYWORDS, PLAYER_EXCLUDED_KEYWORDS_NETEASE, PLAYER_EXCLUDED_KEYWORDS_QQ,
    PLAYER_TITLE_SUFFIXES_NETEASE, PLAYER_TITLE_SUFFIXES_QQ, TITLE_PATTERNS, TITLE_SEPARATORS,
};
use crate::models::SongInfo;

fn segment_split_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\s*[-—–|]\s*").expect("valid segment regex"))
}

fn excluded_lower() -> &'static Vec<String> {
    static RE: OnceLock<Vec<String>> = OnceLock::new();
    RE.get_or_init(|| {
        EXCLUDED_TITLE_KEYWORDS
            .iter()
            .map(|item| item.to_lowercase())
            .collect()
    })
}

fn player_excluded(player_key: &str) -> &'static [&'static str] {
    match player_key {
        "qq" => PLAYER_EXCLUDED_KEYWORDS_QQ,
        "netease" => PLAYER_EXCLUDED_KEYWORDS_NETEASE,
        _ => &[],
    }
}

fn player_suffixes(player_key: &str) -> &'static [&'static str] {
    match player_key {
        "qq" => PLAYER_TITLE_SUFFIXES_QQ,
        "netease" => PLAYER_TITLE_SUFFIXES_NETEASE,
        _ => &[],
    }
}

/// 剥离标题末尾的播放器应用名。
pub fn clean_window_title(title: &str, player_key: &str) -> String {
    let mut cleaned = title.trim().to_string();
    let mut suffixes: Vec<&str> = player_suffixes(player_key).to_vec();
    suffixes.sort_by_key(|item| std::cmp::Reverse(item.chars().count()));

    for suffix in suffixes {
        let pattern = format!(r"\s*[-—–|]\s*{}\s*$", regex::escape(suffix));
        if let Ok(re) = regex::RegexBuilder::new(&pattern)
            .case_insensitive(true)
            .build()
        {
            cleaned = re.replace_all(&cleaned, "").trim().to_string();
        }
    }
    cleaned
}

/// 判断窗口标题是否像“正在播放的歌曲”。
pub fn is_valid_song_title(title: &str, player_key: &str) -> bool {
    if title.is_empty() {
        return false;
    }

    let cleaned = clean_window_title(title, player_key);
    if !TITLE_SEPARATORS.iter().any(|sep| cleaned.contains(sep)) {
        return false;
    }

    let lowered = cleaned.to_lowercase();
    if player_excluded(player_key)
        .iter()
        .any(|keyword| lowered.contains(&keyword.to_lowercase()))
    {
        return false;
    }

    let excluded = excluded_lower();
    !segment_split_re()
        .split(&cleaned)
        .map(|segment| segment.trim().to_lowercase())
        .filter(|segment| !segment.is_empty())
        .any(|segment| excluded.iter().any(|item| item == &segment))
}

/// 把窗口标题解析为 `SongInfo`。
pub fn parse_title(title: &str, player_key: &str) -> Option<SongInfo> {
    if title.is_empty() {
        return None;
    }

    let cleaned = clean_window_title(title, player_key);
    for pattern in TITLE_PATTERNS {
        let re = Regex::new(pattern).ok()?;
        let captures = match re.captures(&cleaned) {
            Some(value) => value,
            None => continue,
        };
        let song_title = captures.get(1).map(|m| m.as_str().trim()).unwrap_or("");
        let artist = captures.get(2).map(|m| m.as_str().trim()).unwrap_or("");
        if song_title.is_empty() || artist.is_empty() {
            continue;
        }
        return Some(SongInfo::new(song_title, artist, player_key));
    }
    None
}

/// 当同一播放器存在多个窗口标题时，选出最可能是歌曲的那个。
pub fn select_best_title(titles: &[String]) -> Option<String> {
    if titles.is_empty() {
        return None;
    }
    if titles.len() == 1 {
        return Some(titles[0].clone());
    }

    let mut best: Option<(i32, &String)> = None;
    for title in titles {
        let mut score = 0i32;
        let length = title.chars().count();
        if (10..=100).contains(&length) {
            score += 10;
        } else if (5..10).contains(&length) || (100..=150).contains(&length) {
            score += 5;
        }

        if title.contains(" - ") {
            score += 15;
        } else if title.contains(" — ") || title.contains(" – ") {
            score += 12;
        } else if title.contains(" | ") {
            score += 8;
        }

        if title.contains('[') || title.contains(']') {
            score -= 3;
        }
        if title.contains('(') && title.contains(')') {
            score -= 2;
        }

        match best {
            None => best = Some((score, title)),
            Some((best_score, _)) if score > best_score => best = Some((score, title)),
            _ => {}
        }
    }
    best.map(|(_, title)| title.clone())
}
