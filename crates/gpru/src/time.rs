use chrono::{Datelike, Local, Timelike, Utc};
use std::path::{Path, PathBuf};

pub fn now_str() -> String {
    Local::now().format("%Y%m%d.%H%M%S").to_string()
}

pub fn now_ts() -> f64 {
    Utc::now().timestamp_millis() as f64 / 1000.0
}

pub fn pretty_timedelta(since_ts: f64) -> String {
    let delta = (now_ts() - since_ts).max(0.0) as i64;
    let days = delta / 86_400;
    let hours = (delta % 86_400) / 3_600;
    let mins = (delta % 3_600) / 60;
    let secs = delta % 60;

    if days > 0 {
        format!("{days}d {hours}h")
    } else if hours > 0 {
        format!("{hours}h {mins}m")
    } else if mins > 0 {
        format!("{mins}m {secs}s")
    } else {
        format!("{secs}s")
    }
}

pub fn prepend_datestamp(path: impl AsRef<Path>, separator: &str) -> PathBuf {
    let p = path.as_ref();
    let stamp = Local::now().format("%y%m%d").to_string();
    let name = p.file_name().unwrap_or_default().to_string_lossy();
    p.with_file_name(format!("{stamp}{separator}{name}"))
}

pub fn append_timestamp(path: impl AsRef<Path>) -> PathBuf {
    let p = path.as_ref();
    let dt = Local::now();
    let ts = format!(
        "{:02}{:02}{:02}-{:02}{:02}",
        dt.year() % 100,
        dt.month(),
        dt.day(),
        dt.hour(),
        dt.minute()
    );

    let stem = p.file_stem().unwrap_or_default().to_string_lossy();
    let ext = p
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    p.with_file_name(format!("{stem}-{ts}{ext}"))
}
