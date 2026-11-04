#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if std::env::args().any(|arg| arg == "--smoke-test") {
        std::process::exit(melodygap_lib::smoke_test());
    }
    melodygap_lib::run()
}
