//! Subsonic / Navidrome API 客户端。

use std::collections::HashMap;
use std::time::Duration;

use md5::{Digest, Md5};
use rand::distributions::Alphanumeric;
use rand::Rng;
use serde_json::Value;
use thiserror::Error;
use url::Url;

use crate::constants::{
    SUBSONIC_API_VERSION, SUBSONIC_CLIENT_NAME, SUBSONIC_REQUEST_TIMEOUT, SUBSONIC_SONG_COUNT_FULL,
    SUBSONIC_SONG_COUNT_SINGLE,
};
use crate::matcher::{should_early_stop, CandidateSong, MatchResult, SongMatcher};

#[derive(Debug, Clone, Error)]
#[error("{message}")]
pub struct SubsonicError {
    pub message: String,
    pub code: i32,
}

impl SubsonicError {
    pub fn new(message: impl Into<String>, code: i32) -> Self {
        Self {
            message: message.into(),
            code,
        }
    }
}

/// 便于监控层注入假实现。
pub trait LibraryClient: Send + Sync {
    fn find_exact_match(&self, artist: &str, title: &str) -> Result<bool, SubsonicError>;
    fn ping(&self) -> Result<ServerInfo, SubsonicError>;
}

#[derive(Clone, Debug, Default)]
pub struct ServerInfo {
    pub server_type: String,
    pub server_version: String,
    pub api_version: String,
}

/// 把用户填写的服务器地址规范为 API 根地址。
pub fn normalize_server_url(server_url: &str) -> String {
    let trimmed = server_url.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        return String::new();
    }

    let Ok(mut url) = Url::parse(trimmed) else {
        return trimmed.to_string();
    };

    let mut path = url.path().trim_end_matches('/').to_string();
    let lowered = path.to_lowercase();
    for suffix in ["/rest/search3", "/rest/search2", "/rest/ping", "/rest"] {
        if lowered.ends_with(suffix) {
            path.truncate(path.len() - suffix.len());
            path = path.trim_end_matches('/').to_string();
            break;
        }
    }
    url.set_path(&path);
    url.set_query(None);
    url.set_fragment(None);
    url.to_string().trim_end_matches('/').to_string()
}

pub struct SubsonicClient {
    pub server_url: String,
    pub username: String,
    pub password: String,
    pub client_name: String,
    pub api_version: String,
    pub verify_ssl: bool,
    pub matcher: SongMatcher,
    client: reqwest::blocking::Client,
}

impl SubsonicClient {
    pub fn new(
        server_url: &str,
        username: &str,
        password: &str,
        client_name: &str,
        timeout_secs: u64,
        verify_ssl: bool,
        matcher: SongMatcher,
    ) -> Result<Self, SubsonicError> {
        let timeout = Duration::from_secs(timeout_secs.max(1));
        let client = reqwest::blocking::Client::builder()
            .timeout(timeout)
            .danger_accept_invalid_certs(!verify_ssl)
            .user_agent(format!("{client_name}/{SUBSONIC_API_VERSION}"))
            .build()
            .map_err(|error| SubsonicError::new(format!("初始化网络客户端失败: {error}"), -3))?;

        Ok(Self {
            server_url: normalize_server_url(server_url),
            username: username.to_string(),
            password: password.to_string(),
            client_name: client_name.to_string(),
            api_version: SUBSONIC_API_VERSION.to_string(),
            verify_ssl,
            matcher,
            client,
        })
    }

    pub fn with_defaults(
        server_url: &str,
        username: &str,
        password: &str,
        verify_ssl: bool,
    ) -> Result<Self, SubsonicError> {
        Self::new(
            server_url,
            username,
            password,
            SUBSONIC_CLIENT_NAME,
            SUBSONIC_REQUEST_TIMEOUT,
            verify_ssl,
            SongMatcher::default(),
        )
    }

    fn generate_token(&self) -> (String, String) {
        let salt: String = rand::thread_rng()
            .sample_iter(&Alphanumeric)
            .take(6)
            .map(char::from)
            .collect();
        let mut hasher = Md5::new();
        hasher.update(format!("{}{}", self.password, salt).as_bytes());
        let token = format!("{:x}", hasher.finalize());
        (token, salt)
    }

    fn make_request(
        &self,
        endpoint: &str,
        params: &[(String, String)],
    ) -> Result<Value, SubsonicError> {
        let (token, salt) = self.generate_token();
        let mut query: Vec<(String, String)> = vec![
            ("u".to_string(), self.username.clone()),
            ("v".to_string(), self.api_version.clone()),
            ("c".to_string(), self.client_name.clone()),
            ("f".to_string(), "json".to_string()),
            ("t".to_string(), token),
            ("s".to_string(), salt),
        ];
        query.extend(params.iter().cloned());

        let url = format!("{}/rest/{}", self.server_url, endpoint);
        let mut response = None;
        for attempt in 0..2 {
            match self.client.get(&url).query(&query).send() {
                Ok(value) => {
                    response = Some(value);
                    break;
                }
                Err(error) => {
                    if (error.is_timeout() || error.is_connect() || error.is_request())
                        && attempt == 0
                    {
                        tracing::debug!(endpoint, %error, "网络请求失败，重试一次");
                        continue;
                    }
                    let text = error.to_string().to_lowercase();
                    if text.contains("certificate") || text.contains("ssl") || text.contains("tls")
                    {
                        return Err(SubsonicError::new(
                            "HTTPS 证书校验失败，请检查证书，或在设置中关闭证书校验",
                            -2,
                        ));
                    }
                    if error.is_timeout() {
                        return Err(SubsonicError::new(
                            "连接超时，请检查服务器地址和网络连接",
                            -1,
                        ));
                    }
                    if error.is_connect() {
                        return Err(SubsonicError::new("连接失败，请检查服务器地址是否正确", -2));
                    }
                    return Err(SubsonicError::new(format!("网络请求失败: {error}"), -3));
                }
            }
        }

        let response = response.ok_or_else(|| SubsonicError::new("网络请求失败", -3))?;
        let status = response.status();
        if status.as_u16() == 401 {
            return Err(SubsonicError::new("认证失败，请检查用户名和密码", 401));
        }
        if status.as_u16() == 404 {
            return Err(SubsonicError::new("服务器地址不存在或路径错误", 404));
        }
        if !status.is_success() {
            return Err(SubsonicError::new(
                format!("HTTP 错误 {}", status.as_u16()),
                status.as_u16() as i32,
            ));
        }

        let data: Value = response
            .json()
            .map_err(|_| SubsonicError::new("服务器响应格式错误，请检查服务器地址", -4))?;
        let payload = data
            .get("subsonic-response")
            .and_then(|item| item.as_object())
            .ok_or_else(|| SubsonicError::new("服务器响应格式错误，请检查服务器地址", -4))?;

        if payload.get("status").and_then(|item| item.as_str()) != Some("ok") {
            let error = payload.get("error");
            let code = error
                .and_then(|item| item.get("code"))
                .and_then(|item| item.as_i64())
                .unwrap_or(0) as i32;
            let message = error
                .and_then(|item| item.get("message"))
                .and_then(|item| item.as_str())
                .unwrap_or("未知错误");
            let text = match code {
                40 => "用户名或密码错误".to_string(),
                50 => "用户未授权访问此资源".to_string(),
                _ => format!("API 错误 ({code}): {message}"),
            };
            return Err(SubsonicError::new(text, code));
        }

        Ok(Value::Object(payload.clone()))
    }

    pub fn ping(&self) -> Result<ServerInfo, SubsonicError> {
        let payload = self.make_request("ping", &[])?;
        Ok(ServerInfo {
            server_type: payload
                .get("type")
                .and_then(|item| item.as_str())
                .unwrap_or("")
                .to_string(),
            server_version: payload
                .get("serverVersion")
                .and_then(|item| item.as_str())
                .unwrap_or("")
                .to_string(),
            api_version: payload
                .get("version")
                .and_then(|item| item.as_str())
                .unwrap_or("")
                .to_string(),
        })
    }

    fn extract_songs(payload: &Value, result_key: &str) -> Vec<CandidateSong> {
        let songs = payload.get(result_key).and_then(|item| item.get("song"));
        match songs {
            Some(Value::Array(items)) => items
                .iter()
                .filter_map(|item| serde_json::from_value::<CandidateSong>(item.clone()).ok())
                .collect(),
            Some(Value::Object(_)) => songs
                .cloned()
                .and_then(|item| serde_json::from_value::<CandidateSong>(item).ok())
                .into_iter()
                .collect(),
            _ => Vec::new(),
        }
    }

    fn search_endpoint(
        &self,
        endpoint: &str,
        result_key: &str,
        query: &str,
        song_count: u32,
    ) -> Result<Vec<CandidateSong>, SubsonicError> {
        let payload = self.make_request(
            endpoint,
            &[
                ("query".to_string(), query.trim().to_string()),
                ("songCount".to_string(), song_count.to_string()),
                ("artistCount".to_string(), "0".to_string()),
                ("albumCount".to_string(), "0".to_string()),
            ],
        )?;
        Ok(Self::extract_songs(&payload, result_key))
    }

    fn search(&self, query: &str, song_count: u32) -> Result<Vec<CandidateSong>, SubsonicError> {
        if query.trim().is_empty() {
            return Ok(Vec::new());
        }
        match self.search_endpoint("search3", "searchResult3", query, song_count) {
            Ok(value) => Ok(value),
            Err(error) if matches!(error.code, 0 | 10 | 70) => {
                tracing::info!(%error, "search3 不可用，尝试 search2");
                self.search_endpoint("search2", "searchResult2", query, song_count)
            }
            Err(error) => Err(error),
        }
    }

    fn merge_unique(unique: &mut HashMap<String, CandidateSong>, songs: Vec<CandidateSong>) {
        for song in songs {
            if song.id.is_empty() {
                continue;
            }
            unique.entry(song.id.clone()).or_insert(song);
        }
    }

    fn search_queries(&self, artist: &str, title: &str) -> [(String, u32); 3] {
        [
            (
                format!("{} {}", artist, title).trim().to_string(),
                SUBSONIC_SONG_COUNT_FULL,
            ),
            (title.to_string(), SUBSONIC_SONG_COUNT_SINGLE),
            (artist.to_string(), SUBSONIC_SONG_COUNT_SINGLE),
        ]
    }

    pub fn search_song(
        &self,
        artist: &str,
        title: &str,
    ) -> Result<Vec<CandidateSong>, SubsonicError> {
        let mut unique = HashMap::new();
        let mut last_error: Option<SubsonicError> = None;

        for (query, song_count) in self.search_queries(artist, title) {
            match self.search(&query, song_count) {
                Ok(songs) => Self::merge_unique(&mut unique, songs),
                Err(error) => {
                    tracing::warn!(%error, query, "搜索失败");
                    last_error = Some(error);
                }
            }
        }

        if unique.is_empty() {
            if let Some(error) = last_error {
                return Err(error);
            }
        }

        let mut songs: Vec<CandidateSong> = unique.into_values().collect();
        songs.sort_by(|left, right| left.id.cmp(&right.id));
        Ok(songs)
    }

    pub fn match_song(&self, artist: &str, title: &str) -> Result<MatchResult, SubsonicError> {
        let mut unique: HashMap<String, CandidateSong> = HashMap::new();
        let mut last_error: Option<SubsonicError> = None;
        let mut result = MatchResult::default();

        for (query, song_count) in self.search_queries(artist, title) {
            match self.search(&query, song_count) {
                Ok(songs) => Self::merge_unique(&mut unique, songs),
                Err(error) => {
                    tracing::warn!(%error, query, "搜索失败");
                    last_error = Some(error);
                    continue;
                }
            }

            let songs: Vec<CandidateSong> = unique.values().cloned().collect();
            result = self.matcher.find_best_match(&songs, artist, title);
            if should_early_stop(&result) {
                tracing::debug!(score = result.score, "提前命中，跳过后续搜索");
                return Ok(result);
            }
        }

        if !result.matched {
            if let Some(error) = last_error {
                return Err(error);
            }
        }
        Ok(result)
    }

    pub fn find_exact_match(&self, artist: &str, title: &str) -> Result<bool, SubsonicError> {
        Ok(self.match_song(artist, title)?.matched)
    }
}

impl LibraryClient for SubsonicClient {
    fn find_exact_match(&self, artist: &str, title: &str) -> Result<bool, SubsonicError> {
        SubsonicClient::find_exact_match(self, artist, title)
    }

    fn ping(&self) -> Result<ServerInfo, SubsonicError> {
        SubsonicClient::ping(self)
    }
}
