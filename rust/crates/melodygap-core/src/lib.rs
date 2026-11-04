//! MelodyGap 核心业务库。
//!
//! 该 crate 不依赖 Tauri 或 Windows API，可在任意平台运行单元测试。

pub mod config;
pub mod constants;
pub mod matcher;
pub mod missing_repository;
pub mod models;
pub mod monitor;
pub mod reminder;
pub mod subsonic;
pub mod title_parser;

pub use config::{AppSettings, ConfigManager, SubsonicConfig};
pub use matcher::{make_song_key, CandidateSong, MatchResult, SongMatcher};
pub use missing_repository::{MissingRepository, RepositoryError};
pub use models::{MissingSong, PlayRecord, PlaybackCandidate, SongInfo};
pub use monitor::{MusicMonitor, PlaybackDetector, RecordCallback};
pub use subsonic::{normalize_server_url, LibraryClient, SubsonicClient, SubsonicError};
pub use title_parser::{clean_window_title, is_valid_song_title, parse_title, select_best_title};
