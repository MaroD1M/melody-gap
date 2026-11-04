//! `config.ini` 读写，兼容 Python 版格式。

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

use chrono::Local;
use thiserror::Error;

use crate::constants::{
    is_valid_reminder_mode, APP_SECTION, CONFIG_FILE_NAME, DEFAULT_LAST_TAB,
    DEFAULT_REMINDER_COOLDOWN_MINUTES, DEFAULT_REMINDER_MODE, SUBSONIC_PLACEHOLDER_SERVER,
    SUBSONIC_SECTION,
};

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("配置文件读写失败: {0}")]
    Io(#[from] io::Error),
    #[error("配置文件格式错误: {0}")]
    Parse(String),
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SubsonicConfig {
    pub server_url: String,
    pub username: String,
    pub password: String,
    pub verify_ssl: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AppSettings {
    pub reminder_mode: String,
    pub reminder_cooldown_minutes: i64,
    pub window_geometry: String,
    pub window_zoomed: bool,
    pub last_tab: i64,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            reminder_mode: DEFAULT_REMINDER_MODE.to_string(),
            reminder_cooldown_minutes: DEFAULT_REMINDER_COOLDOWN_MINUTES,
            window_geometry: String::new(),
            window_zoomed: false,
            last_tab: DEFAULT_LAST_TAB,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct ConfigManager {
    pub path: PathBuf,
    sections: BTreeMap<String, BTreeMap<String, String>>,
}

impl ConfigManager {
    /// 加载配置；文件不存在时创建默认配置。
    pub fn new(path: impl Into<PathBuf>) -> Result<Self, ConfigError> {
        let path = path.into();
        let mut manager = Self {
            path,
            sections: BTreeMap::new(),
        };
        manager.load()?;
        Ok(manager)
    }

    pub fn load(&mut self) -> Result<(), ConfigError> {
        self.sections.clear();
        if !self.path.exists() {
            self.create_default()?;
            return Ok(());
        }

        let bytes = fs::read(&self.path)?;
        let text = String::from_utf8_lossy(&bytes);
        let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
        match parse_ini(text) {
            Ok(sections) => {
                self.sections = sections;
                self.ensure_sections();
                Ok(())
            }
            Err(error) => {
                tracing::error!(%error, "读取配置失败，将备份并使用默认配置");
                self.backup_corrupt();
                self.sections.clear();
                self.create_default()?;
                Ok(())
            }
        }
    }

    fn ensure_sections(&mut self) {
        self.sections
            .entry(SUBSONIC_SECTION.to_string())
            .or_default();
        self.sections.entry(APP_SECTION.to_string()).or_default();
    }

    fn backup_corrupt(&self) {
        if !self.path.exists() {
            return;
        }
        let suffix = Local::now().format("%Y%m%d_%H%M%S_%6f").to_string();
        let file_name = self
            .path
            .file_stem()
            .map(|value| value.to_string_lossy().to_string())
            .unwrap_or_else(|| "config".to_string());
        let backup = self
            .path
            .with_file_name(format!("{file_name}.corrupt_{suffix}.ini"));
        if let Err(error) = fs::rename(&self.path, &backup) {
            tracing::error!(%error, "备份损坏配置失败");
        } else {
            tracing::warn!(path = %backup.display(), "损坏配置已备份");
        }
    }

    fn create_default(&mut self) -> Result<(), ConfigError> {
        self.ensure_sections();
        let subsonic = self.sections.get_mut(SUBSONIC_SECTION).unwrap();
        subsonic.insert(
            "server_url".to_string(),
            format!("{SUBSONIC_PLACEHOLDER_SERVER}:port/"),
        );
        subsonic.insert("username".to_string(), "your_username".to_string());
        subsonic.insert("password".to_string(), "your_password".to_string());
        subsonic.insert("verify_ssl".to_string(), "1".to_string());

        let app = self.sections.get_mut(APP_SECTION).unwrap();
        app.insert(
            "reminder_mode".to_string(),
            DEFAULT_REMINDER_MODE.to_string(),
        );
        app.insert(
            "reminder_cooldown_minutes".to_string(),
            DEFAULT_REMINDER_COOLDOWN_MINUTES.to_string(),
        );
        app.insert("window_geometry".to_string(), String::new());
        app.insert("window_zoomed".to_string(), "0".to_string());
        app.insert("last_tab".to_string(), DEFAULT_LAST_TAB.to_string());
        self.save()?;
        Ok(())
    }

    /// 原子写回配置文件。
    pub fn save(&self) -> Result<(), ConfigError> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let text = serialize_ini(&self.sections);
        let temp_path = self.path.with_file_name(format!(
            "{}.tmp",
            self.path
                .file_name()
                .map(|value| value.to_string_lossy().to_string())
                .unwrap_or_else(|| CONFIG_FILE_NAME.to_string())
        ));
        fs::write(&temp_path, text.as_bytes())?;
        if let Err(error) = fs::rename(&temp_path, &self.path) {
            let _ = fs::remove_file(&self.path);
            if let Err(second) = fs::rename(&temp_path, &self.path) {
                let _ = fs::remove_file(&temp_path);
                return Err(ConfigError::Io(
                    if second.kind() == io::ErrorKind::NotFound {
                        error
                    } else {
                        second
                    },
                ));
            }
        }
        Ok(())
    }

    pub fn get_subsonic_config(&self) -> SubsonicConfig {
        let section = self.sections.get(SUBSONIC_SECTION);
        let get = |key: &str, fallback: &str| {
            section
                .and_then(|map| map.get(key))
                .cloned()
                .unwrap_or_else(|| fallback.to_string())
        };
        SubsonicConfig {
            server_url: get("server_url", ""),
            username: get("username", ""),
            password: get("password", ""),
            verify_ssl: get("verify_ssl", "1") != "0",
        }
    }

    pub fn update_subsonic_config(&mut self, config: &SubsonicConfig) -> Result<(), ConfigError> {
        let section = self
            .sections
            .entry(SUBSONIC_SECTION.to_string())
            .or_default();
        section.insert("server_url".to_string(), config.server_url.clone());
        section.insert("username".to_string(), config.username.clone());
        section.insert("password".to_string(), config.password.clone());
        section.insert(
            "verify_ssl".to_string(),
            if config.verify_ssl { "1" } else { "0" }.to_string(),
        );
        self.save()
    }

    pub fn is_subsonic_configured(&self) -> bool {
        let config = self.get_subsonic_config();
        !config.server_url.is_empty()
            && !config.username.is_empty()
            && !config.password.is_empty()
            && !config.server_url.starts_with(SUBSONIC_PLACEHOLDER_SERVER)
    }

    pub fn get_app_settings(&self) -> AppSettings {
        let section = self.sections.get(APP_SECTION);
        let get = |key: &str, fallback: &str| {
            section
                .and_then(|map| map.get(key))
                .cloned()
                .unwrap_or_else(|| fallback.to_string())
        };

        let mut reminder_mode = get("reminder_mode", DEFAULT_REMINDER_MODE);
        if !is_valid_reminder_mode(&reminder_mode) {
            reminder_mode = DEFAULT_REMINDER_MODE.to_string();
        }

        let cooldown = get(
            "reminder_cooldown_minutes",
            &DEFAULT_REMINDER_COOLDOWN_MINUTES.to_string(),
        )
        .parse::<i64>()
        .unwrap_or(DEFAULT_REMINDER_COOLDOWN_MINUTES)
        .clamp(0, 1440);

        let last_tab = get("last_tab", &DEFAULT_LAST_TAB.to_string())
            .parse::<i64>()
            .unwrap_or(DEFAULT_LAST_TAB)
            .max(0);

        let window_zoomed = matches!(get("window_zoomed", "0").as_str(), "1");

        AppSettings {
            reminder_mode,
            reminder_cooldown_minutes: cooldown,
            window_geometry: get("window_geometry", ""),
            window_zoomed,
            last_tab,
        }
    }

    pub fn update_app_settings(&mut self, settings: &AppSettings) -> Result<(), ConfigError> {
        let section = self.sections.entry(APP_SECTION.to_string()).or_default();
        section.insert("reminder_mode".to_string(), settings.reminder_mode.clone());
        section.insert(
            "reminder_cooldown_minutes".to_string(),
            settings.reminder_cooldown_minutes.to_string(),
        );
        section.insert(
            "window_geometry".to_string(),
            settings.window_geometry.clone(),
        );
        section.insert(
            "window_zoomed".to_string(),
            if settings.window_zoomed { "1" } else { "0" }.to_string(),
        );
        section.insert("last_tab".to_string(), settings.last_tab.to_string());
        self.save()
    }

    pub fn set_window_geometry(&mut self, geometry: &str, zoomed: bool) -> Result<(), ConfigError> {
        let mut settings = self.get_app_settings();
        settings.window_geometry = geometry.to_string();
        settings.window_zoomed = zoomed;
        self.update_app_settings(&settings)
    }

    pub fn set_last_tab(&mut self, tab: i64) -> Result<(), ConfigError> {
        let mut settings = self.get_app_settings();
        settings.last_tab = tab.max(0);
        self.update_app_settings(&settings)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

fn parse_ini(text: &str) -> Result<BTreeMap<String, BTreeMap<String, String>>, ConfigError> {
    let mut sections: BTreeMap<String, BTreeMap<String, String>> = BTreeMap::new();
    let mut current: Option<String> = None;

    for (index, raw_line) in text.lines().enumerate() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
            continue;
        }
        if line.starts_with('[') && line.ends_with(']') {
            let name = line[1..line.len() - 1].trim().to_string();
            if name.is_empty() {
                return Err(ConfigError::Parse(format!(
                    "第 {} 行 section 名称为空",
                    index + 1
                )));
            }
            sections.entry(name.clone()).or_default();
            current = Some(name);
            continue;
        }

        let Some(section) = current.as_ref() else {
            return Err(ConfigError::Parse(format!(
                "第 {} 行缺少 section 头",
                index + 1
            )));
        };

        let delimiter = line
            .find('=')
            .into_iter()
            .chain(line.find(':'))
            .min()
            .ok_or_else(|| ConfigError::Parse(format!("第 {} 行缺少键值分隔符", index + 1)))?;
        let key = line[..delimiter].trim().to_lowercase();
        let value = line[delimiter + 1..].trim().to_string();
        if key.is_empty() {
            return Err(ConfigError::Parse(format!("第 {} 行键名为空", index + 1)));
        }
        sections
            .entry(section.clone())
            .or_default()
            .insert(key, value);
    }

    Ok(sections)
}

fn serialize_ini(sections: &BTreeMap<String, BTreeMap<String, String>>) -> String {
    let mut output = String::new();
    for (section, values) in sections {
        output.push('[');
        output.push_str(section);
        output.push_str("]\n");
        for (key, value) in values {
            output.push_str(key);
            output.push_str(" = ");
            output.push_str(value);
            output.push('\n');
        }
        output.push('\n');
    }
    output
}
