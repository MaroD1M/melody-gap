//! 混合播放检测：SMTC 优先，窗口标题补齐缺失播放器。

use std::collections::HashMap;

use melodygap_core::constants::SUPPORTED_PLAYERS;
use melodygap_core::models::PlaybackCandidate;
use melodygap_core::monitor::PlaybackDetector;

use super::smtc::SmtcDetector;
use super::window::WindowDetector;

pub struct HybridDetector {
    smtc: SmtcDetector,
    window: WindowDetector,
}

impl HybridDetector {
    pub fn new() -> Self {
        Self {
            smtc: SmtcDetector::new(),
            window: WindowDetector::new(),
        }
    }

    pub fn start(&self) {
        let _ = self.smtc.start();
    }

    pub fn stop(&self) {
        self.smtc.stop();
    }

    pub fn smtc_available(&self) -> bool {
        self.smtc.available()
    }

    pub fn smtc_error(&self) -> Option<String> {
        self.smtc.last_error()
    }

    pub fn get_current_playings(&self) -> Vec<PlaybackCandidate> {
        let mut smtc_candidates: HashMap<&'static str, PlaybackCandidate> = HashMap::new();
        for candidate in self.smtc.snapshot() {
            let player = candidate.player().to_string();
            let Some(config) = SUPPORTED_PLAYERS.iter().find(|item| item.key == player) else {
                continue;
            };
            if candidate.title().is_empty() {
                continue;
            }
            smtc_candidates.entry(config.key).or_insert(candidate);
        }

        let needed: Vec<&str> = SUPPORTED_PLAYERS
            .iter()
            .filter(|player| !smtc_candidates.contains_key(player.key))
            .map(|player| player.key)
            .collect();

        let mut window_candidates: HashMap<&'static str, PlaybackCandidate> = HashMap::new();
        if !needed.is_empty() {
            for candidate in self.window.get_current_playings(Some(&needed)) {
                let player = candidate.player().to_string();
                let Some(config) = SUPPORTED_PLAYERS.iter().find(|item| item.key == player) else {
                    continue;
                };
                if candidate.title().is_empty() || smtc_candidates.contains_key(config.key) {
                    continue;
                }
                window_candidates.entry(config.key).or_insert(candidate);
            }
        }

        let mut result = Vec::new();
        for player in SUPPORTED_PLAYERS {
            if let Some(candidate) = smtc_candidates
                .remove(player.key)
                .or_else(|| window_candidates.remove(player.key))
            {
                result.push(candidate);
            }
        }
        result
    }
}

impl Default for HybridDetector {
    fn default() -> Self {
        Self::new()
    }
}

pub struct DetectorHandle(pub std::sync::Arc<HybridDetector>);

impl PlaybackDetector for DetectorHandle {
    fn start(&mut self) {
        self.0.start();
    }

    fn stop(&mut self) {
        self.0.stop();
    }

    fn get_current_playings(&mut self) -> Vec<PlaybackCandidate> {
        self.0.get_current_playings()
    }
}
