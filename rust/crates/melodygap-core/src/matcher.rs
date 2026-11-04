//! 歌曲文本标准化与相似度匹配。
//!
//! 相似度算法移植自 Python `difflib.SequenceMatcher.ratio()`，保持与原版
//! 一致的 Ratcliff/Obershelp 行为。

use std::collections::{HashMap, VecDeque};
use std::sync::OnceLock;

use regex::Regex;
use serde::{Deserialize, Serialize};
use unicode_normalization::UnicodeNormalization;

use crate::constants::{
    ARTIST_WEIGHT, EARLY_STOP_SCORE, MATCH_THRESHOLD, MODIFIER_WORDS_EN, MODIFIER_WORDS_ZH,
    SUBSTRING_MIN_LENGTH, SUBSTRING_SCORE, TITLE_WEIGHT,
};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CandidateSong {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub artist: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct MatchResult {
    pub matched: bool,
    pub song: Option<CandidateSong>,
    pub score: f64,
}

impl Default for MatchResult {
    fn default() -> Self {
        Self {
            matched: false,
            song: None,
            score: 0.0,
        }
    }
}

fn punctuation_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[^\w\s\u{4e00}-\u{9fff}]").expect("valid punctuation regex"))
}

fn modifier_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        let words = MODIFIER_WORDS_EN
            .iter()
            .map(|word| regex::escape(word))
            .collect::<Vec<_>>()
            .join("|");
        Regex::new(&format!(r"(?i)\b(?:{words})\b")).expect("valid modifier regex")
    })
}

/// 标准化文本，消除大小写、全半角、标点、版本修饰词差异。
pub fn normalize_text(text: &str) -> String {
    if text.is_empty() {
        return String::new();
    }

    let text = text.nfkc().collect::<String>().to_lowercase();
    let text = punctuation_re().replace_all(&text, " ");
    let text = modifier_re().replace_all(&text, " ");
    let mut text = text.to_string();
    for word in MODIFIER_WORDS_ZH {
        text = text.replace(word, " ");
    }
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Python difflib 的 `_calculate_ratio`。
fn calculate_ratio(matches: usize, length: usize) -> f64 {
    if length == 0 {
        1.0
    } else {
        2.0 * matches as f64 / length as f64
    }
}

fn find_longest_match(
    a: &[char],
    b: &[char],
    alo: usize,
    ahi: usize,
    blo: usize,
    bhi: usize,
) -> (usize, usize, usize) {
    let mut b2j: HashMap<char, Vec<usize>> = HashMap::new();
    for (j, ch) in b.iter().enumerate().take(bhi).skip(blo) {
        b2j.entry(*ch).or_default().push(j);
    }

    let mut besti = alo;
    let mut bestj = blo;
    let mut bestsize = 0usize;
    let mut j2len: HashMap<usize, usize> = HashMap::new();

    for (i, ch) in a.iter().enumerate().take(ahi).skip(alo) {
        let mut newj2len: HashMap<usize, usize> = HashMap::new();
        if let Some(positions) = b2j.get(ch) {
            for &j in positions {
                if j < blo {
                    continue;
                }
                if j >= bhi {
                    break;
                }
                let previous = if j == 0 {
                    0
                } else {
                    j2len.get(&(j - 1)).copied().unwrap_or(0)
                };
                let k = previous + 1;
                newj2len.insert(j, k);
                if k > bestsize {
                    besti = i + 1 - k;
                    bestj = j + 1 - k;
                    bestsize = k;
                }
            }
        }
        j2len = newj2len;
    }

    while besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1] {
        besti -= 1;
        bestj -= 1;
        bestsize += 1;
    }
    while besti + bestsize < ahi
        && bestj + bestsize < bhi
        && a[besti + bestsize] == b[bestj + bestsize]
    {
        bestsize += 1;
    }

    (besti, bestj, bestsize)
}

fn get_matching_blocks(a: &[char], b: &[char]) -> Vec<(usize, usize, usize)> {
    let mut queue: VecDeque<(usize, usize, usize, usize)> =
        VecDeque::from([(0, a.len(), 0, b.len())]);
    let mut blocks: Vec<(usize, usize, usize)> = Vec::new();

    while let Some((alo, ahi, blo, bhi)) = queue.pop_front() {
        let (i, j, size) = find_longest_match(a, b, alo, ahi, blo, bhi);
        if size > 0 {
            blocks.push((i, j, size));
            if alo < i && blo < j {
                queue.push_back((alo, i, blo, j));
            }
            if i + size < ahi && j + size < bhi {
                queue.push_back((i + size, ahi, j + size, bhi));
            }
        }
    }

    blocks.sort_by_key(|&(i, j, _)| (i, j));

    let mut result: Vec<(usize, usize, usize)> = Vec::new();
    let (mut i, mut j, mut k) = (0usize, 0usize, 0usize);
    for (bi, bj, size) in blocks {
        if i + k == bi && j + k == bj {
            k += size;
        } else {
            if k > 0 {
                result.push((i, j, k));
            }
            i = bi;
            j = bj;
            k = size;
        }
    }
    if k > 0 {
        result.push((i, j, k));
    }
    result.push((a.len(), b.len(), 0));
    result
}

fn sequence_ratio(a: &str, b: &str) -> f64 {
    if a.is_empty() && b.is_empty() {
        return 1.0;
    }
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let blocks = get_matching_blocks(&a_chars, &b_chars);
    let matches: usize = blocks.iter().map(|&(_, _, size)| size).sum();
    calculate_ratio(matches, a_chars.len() + b_chars.len())
}

/// 计算两个已标准化字符串的相似度（0~1）。
pub fn calculate_similarity(text1: &str, text2: &str) -> f64 {
    if text1.is_empty() || text2.is_empty() {
        return 0.0;
    }

    let mut similarity = sequence_ratio(text1, text2);
    let (short, long) = if text1.chars().count() <= text2.chars().count() {
        (text1, text2)
    } else {
        (text2, text1)
    };
    if short.chars().count() >= SUBSTRING_MIN_LENGTH && long.contains(short) {
        similarity = similarity.max(SUBSTRING_SCORE);
    }
    similarity
}

#[derive(Clone, Debug)]
pub struct SongMatcher {
    pub threshold: f64,
    pub artist_weight: f64,
    pub title_weight: f64,
}

impl Default for SongMatcher {
    fn default() -> Self {
        Self {
            threshold: MATCH_THRESHOLD,
            artist_weight: ARTIST_WEIGHT,
            title_weight: TITLE_WEIGHT,
        }
    }
}

impl SongMatcher {
    pub fn new(threshold: f64, artist_weight: f64, title_weight: f64) -> Self {
        Self {
            threshold,
            artist_weight,
            title_weight,
        }
    }

    pub fn normalize_text(text: &str) -> String {
        normalize_text(text)
    }

    pub fn calculate_similarity(text1: &str, text2: &str) -> f64 {
        calculate_similarity(text1, text2)
    }

    pub fn score(
        &self,
        artist: &str,
        title: &str,
        candidate_artist: &str,
        candidate_title: &str,
    ) -> f64 {
        let artist_similarity =
            calculate_similarity(&normalize_text(artist), &normalize_text(candidate_artist));
        let title_similarity =
            calculate_similarity(&normalize_text(title), &normalize_text(candidate_title));
        artist_similarity * self.artist_weight + title_similarity * self.title_weight
    }

    pub fn find_best_match(
        &self,
        songs: &[CandidateSong],
        artist: &str,
        title: &str,
    ) -> MatchResult {
        let normalized_artist = normalize_text(artist);
        let normalized_title = normalize_text(title);
        let mut best_score = 0.0f64;
        let mut best_song: Option<CandidateSong> = None;

        for song in songs {
            let artist_similarity =
                calculate_similarity(&normalized_artist, &normalize_text(&song.artist));
            let title_similarity =
                calculate_similarity(&normalized_title, &normalize_text(&song.title));
            let overall =
                artist_similarity * self.artist_weight + title_similarity * self.title_weight;

            tracing::debug!(
                candidate_artist = %song.artist,
                candidate_title = %song.title,
                artist_score = artist_similarity,
                title_score = title_similarity,
                overall,
                "匹配候选"
            );

            if overall > best_score {
                best_score = overall;
                best_song = Some(song.clone());
            }
        }

        let matched = best_song.is_some() && best_score >= self.threshold;
        if matched {
            if let Some(song) = &best_song {
                tracing::info!(
                    artist = %song.artist,
                    title = %song.title,
                    score = best_score,
                    "匹配成功"
                );
            }
        }
        MatchResult {
            matched,
            song: best_song,
            score: best_score,
        }
    }
}

/// 生成待补清单去重键。
pub fn make_song_key(artist: &str, title: &str) -> String {
    format!("{}|{}", normalize_text(artist), normalize_text(title))
}

pub fn should_early_stop(result: &MatchResult) -> bool {
    result.matched && result.score >= EARLY_STOP_SCORE
}
