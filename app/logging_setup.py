# -*- coding: utf-8 -*-
"""日志初始化。

统一用 logging 替代散落的 ``print``：
* 控制台输出便于开发调试；
* 滚动文件日志便于用户反馈问题时排查（默认 1MB × 3 份）。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from app.constants import APP_NAME, LOG_FILE_NAME

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_dir: Optional[Path] = None, level: int = logging.INFO) -> logging.Logger:
    """初始化根日志器（幂等，重复调用不会重复添加 handler）。

    Args:
        log_dir: 日志文件目录；为空则只输出到控制台。
        level: 日志级别。

    Returns:
        应用根日志器。
    """
    root = logging.getLogger()
    if getattr(root, "_mlm_configured", False):
        return logging.getLogger(APP_NAME)

    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # PyInstaller --windowed 模式下 sys.stdout/stderr 可能为 None，
    # 此时跳过控制台 handler，只写文件日志。
    if sys.stdout is not None:
        # 重定向到非 UTF-8 代码页时，中文日志可能触发 UnicodeEncodeError
        # 并打断启动流程；保留当前编码，只替换无法编码的字符。
        try:
            sys.stdout.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
        console = logging.StreamHandler(stream=sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / LOG_FILE_NAME,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            # 目录只读或磁盘异常时降级为仅控制台，不影响主流程
            root.warning("无法创建日志文件，仅输出到控制台: %s", exc)

    # 降低第三方库噪音（requests/urllib3）
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    setattr(root, "_mlm_configured", True)
    return logging.getLogger(APP_NAME)
