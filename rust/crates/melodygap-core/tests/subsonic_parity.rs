use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, Once};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use md5::{Digest, Md5};
use melodygap_core::matcher::SongMatcher;
use melodygap_core::subsonic::{normalize_server_url, SubsonicClient};
use serde_json::{json, Value};
use url::Url;

type Requests = Arc<Mutex<Vec<(String, HashMap<String, String>)>>>;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    Ok,
    Error,
    Search3Unsupported,
}

struct TestServer {
    addr: SocketAddr,
    requests: Requests,
    responses: Arc<Mutex<HashMap<String, Vec<Value>>>>,
    mode: Arc<Mutex<Mode>>,
    stop: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
}

impl TestServer {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let addr = listener.local_addr().unwrap();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let responses = Arc::new(Mutex::new(HashMap::new()));
        let mode = Arc::new(Mutex::new(Mode::Ok));
        let stop = Arc::new(AtomicBool::new(false));

        let thread_requests = Arc::clone(&requests);
        let thread_responses = Arc::clone(&responses);
        let thread_mode = Arc::clone(&mode);
        let thread_stop = Arc::clone(&stop);
        let handle = thread::spawn(move || {
            while !thread_stop.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        let requests = Arc::clone(&thread_requests);
                        let responses = Arc::clone(&thread_responses);
                        let mode = Arc::clone(&thread_mode);
                        let _ = thread::Builder::new()
                            .name("SubsonicTestConnection".into())
                            .spawn(move || handle_connection(stream, &requests, &responses, &mode));
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(5));
                    }
                    Err(_) => break,
                }
            }
        });

        Self {
            addr,
            requests,
            responses,
            mode,
            stop,
            handle: Some(handle),
        }
    }

    fn url(&self) -> String {
        format!("http://{}/", self.addr)
    }

    fn set_mode(&self, mode: Mode) {
        *self.mode.lock().unwrap() = mode;
    }

    fn set_responses(&self, responses: HashMap<String, Vec<Value>>) {
        *self.responses.lock().unwrap() = responses;
    }

    fn requests(&self) -> Vec<(String, HashMap<String, String>)> {
        self.requests.lock().unwrap().clone()
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

fn handle_connection(
    stream: TcpStream,
    requests: &Requests,
    responses: &Arc<Mutex<HashMap<String, Vec<Value>>>>,
    mode: &Arc<Mutex<Mode>>,
) {
    let Ok(reader_stream) = stream.try_clone() else {
        return;
    };
    let mut reader = BufReader::new(reader_stream);
    let mut writer = stream;
    let mut request_line = String::new();
    if reader.read_line(&mut request_line).is_err() {
        return;
    }
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line).is_err() || line == "\r\n" || line.is_empty() {
            break;
        }
    }

    let target = request_line.split_whitespace().nth(1).unwrap_or("/");
    let Ok(url) = Url::parse(&format!("http://localhost{target}")) else {
        return;
    };
    let path = url.path().to_string();
    let params: HashMap<String, String> = url
        .query_pairs()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();
    requests
        .lock()
        .unwrap()
        .push((path.clone(), params.clone()));

    let current_mode = *mode.lock().unwrap();
    let payload = if current_mode == Mode::Search3Unsupported && path.ends_with("/rest/search3") {
        json!({
            "subsonic-response": {
                "status": "failed",
                "version": "1.16.1",
                "error": {"code": 70, "message": "Search not supported"}
            }
        })
    } else if current_mode == Mode::Error {
        json!({
            "subsonic-response": {
                "status": "failed",
                "version": "1.16.1",
                "error": {"code": 40, "message": "Wrong username or password"}
            }
        })
    } else {
        let query = params.get("query").cloned().unwrap_or_default();
        let songs = responses
            .lock()
            .unwrap()
            .get(&query)
            .cloned()
            .unwrap_or_default();
        let song_value = if songs.len() == 1 {
            songs[0].clone()
        } else {
            Value::Array(songs)
        };
        let result_key = if path.ends_with("/rest/search2") {
            "searchResult2"
        } else {
            "searchResult3"
        };
        let mut response = serde_json::Map::new();
        response.insert("status".into(), json!("ok"));
        response.insert("version".into(), json!("1.16.1"));
        response.insert("type".into(), json!("navidrome"));
        response.insert("serverVersion".into(), json!("0.53.0"));
        response.insert(result_key.into(), json!({"song": song_value}));
        json!({"subsonic-response": Value::Object(response)})
    };

    let body = serde_json::to_vec(&payload).unwrap();
    let header = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let _ = writer.write_all(header.as_bytes());
    let _ = writer.write_all(&body);
    let _ = writer.flush();
    let _ = writer.shutdown(std::net::Shutdown::Both);
}

fn song_a() -> Value {
    json!({"id": "1", "title": "晴天", "artist": "周杰伦", "album": "叶惠美"})
}

fn song_b() -> Value {
    json!({"id": "2", "title": "稻香", "artist": "周杰伦", "album": "魔杰座"})
}

fn song_c() -> Value {
    json!({"id": "3", "title": "晴天 (Live)", "artist": "周杰伦", "album": "演唱会"})
}

fn song_d() -> Value {
    json!({"id": "4", "title": "七里香", "artist": "周杰伦", "album": "七里香"})
}

fn default_responses() -> HashMap<String, Vec<Value>> {
    HashMap::from([
        ("周杰伦 晴天".to_string(), vec![song_a(), song_b()]),
        ("晴天".to_string(), vec![song_a(), song_c()]),
        ("周杰伦".to_string(), vec![song_b(), song_d()]),
    ])
}

fn setup() -> (TestServer, SubsonicClient) {
    static PROXY_ONCE: Once = Once::new();
    PROXY_ONCE.call_once(|| {
        std::env::set_var("NO_PROXY", "127.0.0.1,localhost");
        std::env::set_var("no_proxy", "127.0.0.1,localhost");
    });

    let server = TestServer::start();
    server.set_responses(default_responses());
    let client = SubsonicClient::with_defaults(&server.url(), "demo", "secret", true).unwrap();
    (server, client)
}

#[test]
fn subsonic_normalizes_server_url() {
    assert_eq!(
        normalize_server_url(" https://music.example.com/rest/search3/?x=1 "),
        "https://music.example.com"
    );
    assert_eq!(
        normalize_server_url("https://music.example.com/sub/rest/ping"),
        "https://music.example.com/sub"
    );
    assert_eq!(normalize_server_url(""), "");
}

#[test]
fn subsonic_ping_returns_server_info() {
    let (server, client) = setup();
    let info = client.ping().unwrap();
    assert_eq!(info.api_version, "1.16.1");
    assert_eq!(info.server_type, "navidrome");
    assert_eq!(server.requests()[0].0, "/rest/ping");
}

#[test]
fn subsonic_uses_token_authentication() {
    let (server, client) = setup();
    client.search_song("周杰伦", "晴天").unwrap();
    let requests = server.requests();
    let (_path, params) = &requests[0];
    let salt = params.get("s").expect("salt");
    let expected = format!("{:x}", Md5::digest(format!("secret{salt}").as_bytes()));
    assert_eq!(params.get("t"), Some(&expected));
    assert_eq!(params.get("u").map(String::as_str), Some("demo"));
    assert_eq!(params.get("f").map(String::as_str), Some("json"));
    assert!(!params.contains_key("p"));
}

#[test]
fn subsonic_search_deduplicates_by_song_id() {
    let (server, client) = setup();
    let songs = client.search_song("周杰伦", "晴天").unwrap();
    let ids: Vec<&str> = songs.iter().map(|song| song.id.as_str()).collect();
    assert_eq!(ids, ["1", "2", "3", "4"]);
    assert_eq!(server.requests().len(), 3);
}

#[test]
fn subsonic_search_handles_single_song_dict() {
    let (server, client) = setup();
    server.set_responses(HashMap::from([("晴天".to_string(), vec![song_a()])]));
    let songs = client.search_song("未知歌手", "晴天").unwrap();
    assert_eq!(songs.len(), 1);
    assert_eq!(songs[0].id, "1");
}

#[test]
fn subsonic_find_exact_match() {
    let (_server, client) = setup();
    assert!(client.find_exact_match("周杰伦", "晴天").unwrap());
}

#[test]
fn subsonic_find_exact_match_early_stop() {
    let (server, client) = setup();
    assert!(client.find_exact_match("周杰伦", "晴天").unwrap());
    assert_eq!(server.requests().len(), 1);
}

#[test]
fn subsonic_search3_falls_back_to_search2() {
    let (server, client) = setup();
    server.set_mode(Mode::Search3Unsupported);
    server.set_responses(HashMap::from([("周杰伦 晴天".to_string(), vec![song_a()])]));
    assert!(client.find_exact_match("周杰伦", "晴天").unwrap());
    let paths: Vec<String> = server
        .requests()
        .into_iter()
        .map(|(path, _params)| path)
        .collect();
    assert_eq!(paths[..2], ["/rest/search3", "/rest/search2"]);
}

#[test]
fn subsonic_find_exact_match_propagates_error() {
    let (server, client) = setup();
    server.set_mode(Mode::Error);
    let error = client.find_exact_match("周杰伦", "晴天").unwrap_err();
    assert!(error.to_string().contains("用户名或密码错误"));
}

#[test]
fn subsonic_find_exact_match_negative() {
    let (server, client) = setup();
    server.set_responses(HashMap::from([("周杰伦 晴天".to_string(), vec![song_d()])]));
    assert!(!client.find_exact_match("周杰伦", "晴天").unwrap());
}

#[test]
fn subsonic_ping_propagates_api_error() {
    let (server, client) = setup();
    server.set_mode(Mode::Error);
    let error = client.ping().unwrap_err();
    assert!(error.to_string().contains("用户名或密码错误"));
}

#[test]
fn subsonic_client_constructor_sets_fields() {
    let client = SubsonicClient::new(
        "https://music.example.com/rest/",
        "demo",
        "secret",
        "MelodyGap",
        10,
        false,
        SongMatcher::default(),
    )
    .unwrap();
    assert_eq!(client.server_url, "https://music.example.com");
    assert_eq!(client.username, "demo");
    assert!(!client.verify_ssl);
    assert_eq!(client.api_version, "1.16.1");
}
