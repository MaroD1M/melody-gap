use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("repository root")
        .to_path_buf()
}

fn read(relative: &str) -> String {
    fs::read_to_string(repo_root().join(relative))
        .unwrap_or_else(|error| panic!("读取 {relative} 失败: {error}"))
}

fn workspace_version() -> String {
    let cargo = read("rust/Cargo.toml");
    let mut lines = cargo
        .lines()
        .skip_while(|line| line.trim() != "[workspace.package]")
        .skip(1);
    lines
        .find_map(|line| line.trim().strip_prefix("version = \"")?.strip_suffix('"'))
        .map(str::to_string)
        .expect("workspace.package.version")
}

fn assert_version(value: &str) {
    let parts: Vec<&str> = value.split('.').collect();
    assert_eq!(parts.len(), 3, "版本号格式错误: {value}");
    assert!(
        parts.iter().all(|part| part.parse::<u32>().is_ok()),
        "版本号格式错误: {value}"
    );
}

#[test]
fn package_versions_match() {
    let expected = workspace_version();
    assert_version(&expected);

    let tauri: Value =
        serde_json::from_str(&read("rust/src-tauri/tauri.conf.json")).expect("tauri.conf.json");
    let package: Value = serde_json::from_str(&read("rust/package.json")).expect("package.json");
    let constants = read("rust/crates/melodygap-core/src/constants.rs");
    let app_version = constants
        .lines()
        .find_map(|line| {
            line.trim()
                .strip_prefix("pub const APP_VERSION: &str = \"")?
                .strip_suffix("\";")
        })
        .expect("APP_VERSION");

    assert_eq!(tauri["version"].as_str(), Some(expected.as_str()));
    assert_eq!(package["version"].as_str(), Some(expected.as_str()));
    assert_eq!(app_version, expected);
}

#[test]
fn tauri_uses_portable_data_directory() {
    let config: Value =
        serde_json::from_str(&read("rust/src-tauri/tauri.conf.json")).expect("tauri.conf.json");

    assert_eq!(
        config["app"]["appDirectoriesOverride"]["localData"].as_str(),
        Some("./webview2-data")
    );
    assert_eq!(config["bundle"]["active"].as_bool(), Some(false));
}

#[test]
fn release_workflow_builds_verified_portable_assets() {
    let workflow = read(".github/workflows/release.yml");
    let cargo = read("rust/src-tauri/Cargo.toml");

    for needle in [
        "--features custom-protocol",
        "cargo build --release",
        "pnpm build",
        "cargo test --workspace",
        "MelodyGap-portable-windows-x64.zip",
        "SHA256SUMS.txt",
        "--smoke-test",
        "/assets/index-",
        "CompanyName",
        "OriginalFilename",
    ] {
        assert!(workflow.contains(needle), "Release 工作流缺少 {needle}");
    }
    assert!(cargo.contains("custom-protocol"));
    assert!(!workflow.to_lowercase().contains("pyinstaller"));
    assert!(!workflow.to_lowercase().contains("setup-python"));
}

#[test]
fn ci_runs_rust_quality_checks() {
    let workflow = read(".github/workflows/ci.yml");

    for needle in [
        "cargo fmt --all -- --check",
        "cargo clippy --workspace --all-targets -- -D warnings",
        "cargo test --workspace",
        "pnpm check",
        "pnpm build",
        "/assets/index-",
    ] {
        assert!(workflow.contains(needle), "CI 工作流缺少 {needle}");
    }
    assert!(!workflow.to_lowercase().contains("setup-python"));
}

#[test]
fn main_window_is_created_after_state_is_managed() {
    let config: Value =
        serde_json::from_str(&read("rust/src-tauri/tauri.conf.json")).expect("tauri.conf.json");
    let main = config["app"]["windows"]
        .as_array()
        .expect("windows")
        .iter()
        .find(|window| window["label"].as_str() == Some("main"))
        .expect("main window");

    assert_eq!(main["create"].as_bool(), Some(false));
    assert_eq!(main["visible"].as_bool(), Some(false));
    assert_eq!(main["minWidth"].as_u64(), Some(840));
    assert_eq!(main["minHeight"].as_u64(), Some(540));

    let source = read("rust/src-tauri/src/lib.rs");
    let setup = source
        .split(".setup(|app| {")
        .nth(1)
        .expect("setup")
        .split("commands::install_record_callback")
        .next()
        .expect("setup body");
    let managed_state = setup
        .find("app.manage(state.clone())")
        .expect("manage state");
    let managed_notifications = setup
        .find("state.notifications.set(notifications)")
        .expect("manage notifications");
    let created_window = setup
        .find("create_main_window(app)?")
        .expect("create main window");

    assert!(managed_state < created_window);
    assert!(managed_notifications < created_window);
}
