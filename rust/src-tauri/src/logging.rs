//! 滚动日志：单文件 1MB，保留 3 份备份。

use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use tracing_subscriber::fmt::writer::MakeWriter;

const MAX_BYTES: u64 = 1024 * 1024;
const KEEP_FILES: usize = 3;

#[derive(Clone)]
pub struct RollingFileWriter {
    path: PathBuf,
    lock: Arc<Mutex<()>>,
}

impl RollingFileWriter {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self {
            path: path.into(),
            lock: Arc::new(Mutex::new(())),
        }
    }

    fn rotate_if_needed(&self, incoming: usize) {
        let Ok(metadata) = fs::metadata(&self.path) else {
            return;
        };
        if metadata.len() + incoming as u64 <= MAX_BYTES {
            return;
        }

        let _ = fs::remove_file(backup_path(&self.path, KEEP_FILES));
        for index in (1..KEEP_FILES).rev() {
            let from = backup_path(&self.path, index);
            let to = backup_path(&self.path, index + 1);
            if from.exists() {
                let _ = fs::rename(from, to);
            }
        }
        let _ = fs::rename(&self.path, backup_path(&self.path, 1));
    }
}

fn backup_path(path: &Path, index: usize) -> PathBuf {
    PathBuf::from(format!("{}.{}", path.display(), index))
}

pub struct RollingFileHandle {
    writer: RollingFileWriter,
}

impl Write for RollingFileHandle {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let _guard = self.writer.lock.lock().expect("log lock");
        self.writer.rotate_if_needed(buf.len());
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.writer.path)?;
        file.write_all(buf)?;
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl<'a> MakeWriter<'a> for RollingFileWriter {
    type Writer = RollingFileHandle;

    fn make_writer(&'a self) -> Self::Writer {
        RollingFileHandle {
            writer: self.clone(),
        }
    }
}

pub fn init(app_dir: &Path) {
    let path = app_dir.join("melodygap.log");
    let writer = RollingFileWriter::new(path);
    let _ = tracing_subscriber::fmt()
        .with_writer(writer)
        .with_ansi(false)
        .with_target(true)
        .with_thread_names(true)
        .try_init();
}
