fn main() {
    tauri_build::build();

    // 防止发布版误用 devUrl：Tauri 只有在启用 custom-protocol 时才会嵌入 dist。
    if std::env::var("PROFILE").as_deref() == Ok("release")
        && std::env::var_os("CARGO_FEATURE_CUSTOM_PROTOCOL").is_none()
    {
        panic!(
            "release build requires --features custom-protocol; \
             otherwise the executable will try to open http://localhost:5173"
        );
    }
}
