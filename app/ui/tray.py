# -*- coding: utf-8 -*-
"""应用入口与系统托盘。

线程模型
--------
Tkinter 只能在创建它的线程（主线程）中操作。本项目共有三个线程：

================  ====================================================
线程              职责
================  ====================================================
主线程（Tk）      创建所有窗口、消费 UI 事件队列、定时刷新
监控线程          MusicMonitor 轮询播放器，只写数据 + 投递事件
托盘线程          pystray 消息循环（菜单点击回调在此线程）
================  ====================================================

跨线程通信统一走 ``self._ui_queue``：

* 监控线程检测到新歌 -> ``queue.put(("record", (record, entry, created)))``
* 核验线程逐首返回结果 -> ``queue.put(("recheck_result", (...)))``
* 核验线程结束 -> ``queue.put(("recheck_done", counts))``
* 托盘线程点击“显示主界面” -> ``queue.put(("show", None))``
* 托盘线程点击“待补清单” -> ``queue.put(("show_missing", None))``
* 托盘线程点击“退出程序” -> ``queue.put(("quit", None))``

主线程每 100ms 调用 ``_drain_ui_queue`` 消费队列。**任何线程都不直接调用
Tk 控件方法**，从而修复旧版“监控线程弹通知导致随机崩溃”的问题。
"""

import atexit
import logging
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from app.config_manager import ConfigManager
from app.constants import (
    APP_DISPLAY_NAME,
    APP_NAME,
    CONFIG_FILE_NAME,
    MISSING_FILE_NAME,
)
from app.models import MissingSong, PlayRecord, SongInfo
from app.paths import get_app_dir
from app.services.missing_repository import MissingRepository
from app.services.matcher import make_song_key
from app.services.monitor import MusicMonitor
from app.services.reminder import should_notify
from app.ui.icons import create_tray_image
from app.ui.main_window import MainWindow
from app.ui.notification import NotificationWindow

logger = logging.getLogger(__name__)

# UI 事件队列元素：(kind, payload)
# kind:
#   "record"          -> (PlayRecord, MissingSong | None, created)
#   "recheck_result"  -> (key, title, artist, Optional[bool], quiet)
#   "recheck_done"    -> {"total": int, "in_library": int, ...}
#   "current_recheck_result" -> (SongInfo, Optional[bool])
#   "show" / "show_missing" / "quit" -> None
UiEvent = Tuple[str, object]


class TrayApp:
    """应用生命周期管理器（组合根）。

    负责创建配置、监控、窗口、托盘，并保证资源按顺序释放。
    """

    def __init__(self, app_dir: Optional[Path] = None) -> None:
        self.app_dir = Path(app_dir) if app_dir else get_app_dir()

        self.config_manager = ConfigManager(self.app_dir / CONFIG_FILE_NAME)
        self.missing_repo = MissingRepository(self.app_dir / MISSING_FILE_NAME)

        # 根窗口只用于事件循环，保持隐藏；主界面是 Toplevel
        self.root = tk.Tk()
        self.root.withdraw()

        self._ui_queue: "queue.Queue[UiEvent]" = queue.Queue()
        self._drain_job: Optional[str] = None
        self._last_notified = {}
        self._rechecking = False

        self.notification = NotificationWindow(self.root)
        self.monitor = MusicMonitor(self.config_manager, on_record=self._on_record)
        self.main_window = MainWindow(self.root, self.monitor, self)

        self.icon = None
        self.is_quitting = False
        self._cleaned = False

        atexit.register(self.cleanup_resources)

    # ---------- 跨线程事件 ----------

    def _on_record(self, record: PlayRecord, _song: SongInfo) -> None:
        """监控线程回调：更新待补清单后入队，不操作 UI。"""
        entry = None
        created = False
        if record.in_library is False:
            entry, created = self.missing_repo.add_missing(record)
        elif record.in_library is True:
            self.missing_repo.resolve_song(record.artist, record.title)
        self._ui_queue.put(("record", (record, entry, created)))

    def _drain_ui_queue(self) -> None:
        """主线程消费 UI 事件队列。"""
        self._drain_job = None
        if self.is_quitting:
            return

        while True:
            try:
                kind, payload = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            try:
                if kind == "record" and isinstance(payload, tuple):
                    self._handle_record_ui(*payload)
                elif kind == "recheck_result" and isinstance(payload, tuple):
                    self._handle_recheck_result(*payload)
                elif kind == "recheck_done" and isinstance(payload, dict):
                    self._handle_recheck_done(payload)
                elif kind == "current_recheck_result" and isinstance(payload, tuple):
                    self._handle_current_recheck_result(*payload)
                elif kind == "show":
                    self.main_window.show_window()
                elif kind == "show_missing":
                    self.main_window.show_missing_tab()
                elif kind == "quit":
                    self._do_quit()
                    return
            except Exception:
                logger.exception("处理 UI 事件失败: kind=%s", kind)

        if not self.is_quitting:
            self._drain_job = self.root.after(100, self._drain_ui_queue)

    def _handle_record_ui(
        self,
        record: PlayRecord,
        _entry: Optional[MissingSong],
        created: bool,
    ) -> None:
        """主线程：按提醒策略决定是否弹窗。"""
        settings = self.config_manager.get_reminder_settings()
        mode = str(settings["mode"])
        cooldown_minutes = int(settings["cooldown_minutes"])
        key = make_song_key(record.artist, record.title)
        now = datetime.now()

        if not should_notify(
            mode,
            record.in_library,
            created,
            self._last_notified.get(key),
            now,
            cooldown_minutes,
        ):
            return

        self.notification.show(
            record.title,
            record.artist,
            record.in_library,
            record.player,
            is_new_missing=created,
            copy_text=f"{record.title} - {record.artist}",
        )
        self._last_notified[key] = now

    def _handle_recheck_result(
        self,
        key: str,
        title: str,
        artist: str,
        result: Optional[bool],
        quiet: bool = False,
    ) -> None:
        """主线程：应用“核验”结果。"""
        self.monitor.update_current_result(artist, title, result)
        if result is True:
            self.missing_repo.remove_key(key)
        if quiet:
            return

        if result is True:
            self.notification.show(title, artist, True, copy_text="")
        elif result is False:
            self.notification.show(
                title,
                artist,
                False,
                is_new_missing=False,
                copy_text=f"{title} - {artist}",
            )
        else:
            self.notification.show(title, artist, None, copy_text="")

    def _handle_recheck_done(self, counts: dict) -> None:
        """主线程：批量核验结束，显示汇总。"""
        self._rechecking = False
        message = (
            f"核验完成：已入库 {counts.get('in_library', 0)} 首，"
            f"仍缺失 {counts.get('missing', 0)} 首，"
            f"查询失败 {counts.get('unknown', 0)} 首"
        )
        self.main_window.set_message(message)
        self.main_window.refresh_data()

    def _handle_current_recheck_result(
        self, song: SongInfo, result: Optional[bool]
    ) -> None:
        """主线程：应用当前歌曲的单次重新查询结果。"""
        self._rechecking = False
        if not self.monitor.update_current_result(song.artist, song.title, result):
            self.main_window.set_message("歌曲已切换，本次查询结果未应用")
            self.main_window.refresh_data()
            return
        if result is True:
            self.missing_repo.resolve_song(song.artist, song.title)
            self.main_window.set_message("查询完成：已在曲库")
        elif result is False:
            record = self.monitor.current_record
            if record is not None:
                self.missing_repo.ensure_missing(record)
            self.main_window.set_message("查询完成：不在曲库")
        else:
            error = self.monitor.last_query_error or "未知错误"
            self.main_window.set_message(f"查询失败：{error}")
        self.main_window.refresh_data()

    def _cancel_drain_job(self) -> None:
        if self._drain_job is None:
            return
        try:
            self.root.after_cancel(self._drain_job)
        except tk.TclError:
            pass
        finally:
            self._drain_job = None

    # ---------- 托盘菜单回调（托盘线程） ----------

    def show_main_window(self, icon=None, item=None) -> None:
        """请求显示主界面（可从任意线程调用）。"""
        self._ui_queue.put(("show", None))

    def show_missing_list(self, icon=None, item=None) -> None:
        """请求显示主界面并切到待补清单。"""
        self._ui_queue.put(("show_missing", None))

    def toggle_monitoring(self, icon=None, item=None) -> None:
        """开始/停止监控（MusicMonitor 内部已加锁，跨线程安全）。"""
        if self.monitor.running:
            self.monitor.stop()
        else:
            self.monitor.start()

    def request_close(self) -> None:
        """主窗口关闭按钮策略：有托盘则隐藏，否则直接退出。"""
        if self.icon is not None:
            self.main_window.hide_window()
        else:
            self.quit_app()

    def quit_app(self, icon=None, item=None) -> None:
        """请求退出（可从任意线程调用）。"""
        if self.is_quitting:
            return
        self._ui_queue.put(("quit", None))

    # ---------- 配置 ----------

    def on_config_changed(self) -> None:
        """设置保存后回调：重建 Subsonic 客户端并提示主窗口。"""
        self.monitor.reload_config()
        self.main_window.set_message("设置已保存，服务器配置已生效")

    # ---------- 待补清单 ----------

    def request_recheck_song(self, song: SongInfo) -> None:
        """在后台重新查询一首歌，不要求它已在待补清单中。"""
        if self._rechecking:
            self.main_window.set_message("已有核验任务正在进行，请稍候")
            return
        self._rechecking = True

        def worker() -> None:
            result = self.monitor.recheck_song(song)
            self._ui_queue.put(("current_recheck_result", (song, result)))

        threading.Thread(
            target=worker, name="CurrentRecheck", daemon=True
        ).start()

    def request_recheck(
        self, entries: List[MissingSong], quiet: bool = False
    ) -> None:
        """在后台逐首重查，避免阻塞 UI。

        Args:
            entries: 待核验歌曲
            quiet: 为 True 时不逐首弹窗，结束后只显示一条汇总
        """
        if not entries:
            return
        if self._rechecking:
            self.main_window.set_message("已有核验任务正在进行，请稍候")
            return
        self._rechecking = True
        thread = threading.Thread(
            target=self._recheck_worker,
            args=(list(entries), quiet),
            name="MissingRecheck",
            daemon=True,
        )
        thread.start()

    def _recheck_worker(self, entries: List[MissingSong], quiet: bool) -> None:
        counts = {"total": 0, "in_library": 0, "missing": 0, "unknown": 0}
        for entry in entries:
            if self.is_quitting:
                return
            song = SongInfo(
                title=entry.title,
                artist=entry.artist,
                player=entry.player,
            )
            result = self.monitor.recheck_song(song)
            counts["total"] += 1
            if result is True:
                counts["in_library"] += 1
            elif result is False:
                counts["missing"] += 1
            else:
                counts["unknown"] += 1
            self._ui_queue.put(
                (
                    "recheck_result",
                    (entry.key, entry.title, entry.artist, result, quiet),
                )
            )
        self._ui_queue.put(("recheck_done", counts))

    # ---------- 托盘 ----------

    def setup_tray(self) -> None:
        """创建托盘图标；失败时降级为纯窗口模式。"""
        try:
            import pystray
        except Exception as exc:
            logger.error("加载 pystray 失败，将在无托盘模式下运行: %s", exc)
            self.icon = None
            return

        try:
            menu = pystray.Menu(
                pystray.MenuItem("显示主界面", self.show_main_window, default=True),
                pystray.MenuItem(
                    lambda _text: (
                        "停止监控" if self.monitor.running else "开始监控"
                    ),
                    self.toggle_monitoring,
                ),
                pystray.MenuItem(
                    lambda _text: f"待补清单 ({self.missing_repo.count_pending()})",
                    self.show_missing_list,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self.quit_app),
            )
            self.icon = pystray.Icon(
                APP_NAME,
                create_tray_image(),
                f"♪ {APP_DISPLAY_NAME}",
                menu,
            )
        except Exception:
            logger.exception("创建托盘图标失败，将在无托盘模式下运行")
            self.icon = None

    def _run_tray(self) -> None:
        try:
            assert self.icon is not None
            self.icon.run()
        except Exception:
            logger.exception("托盘图标运行异常")

    # ---------- 生命周期 ----------

    def run(self) -> None:
        """启动监控、托盘与 Tk 主循环。"""
        self.setup_tray()
        self.monitor.start()
        self.main_window.show_window()

        self._drain_job = self.root.after(100, self._drain_ui_queue)

        if self.icon is not None:
            threading.Thread(
                target=self._run_tray, name="TrayIcon", daemon=True
            ).start()
        else:
            logger.warning("托盘不可用，关闭主窗口将直接退出程序")

        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            logger.info("收到 Ctrl+C，准备退出")
        finally:
            if not self.is_quitting:
                self._do_quit()

    def _do_quit(self) -> None:
        """在主线程完成退出（幂等）。"""
        if self.is_quitting:
            return
        self.is_quitting = True
        self._cancel_drain_job()

        logger.info("正在退出程序...")
        self.cleanup_resources()

        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

        logger.info("程序已退出")

    def cleanup_resources(self) -> None:
        """释放监控线程、窗口和托盘资源（幂等，可被 atexit 调用）。"""
        if self._cleaned:
            return
        self._cleaned = True

        try:
            self.monitor.stop()
        except Exception:
            logger.exception("停止监控失败")

        try:
            self.main_window.destroy_window()
        except Exception:
            logger.exception("销毁主窗口失败")

        try:
            self.notification.close()
        except Exception:
            logger.exception("关闭通知窗口失败")

        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                logger.exception("停止托盘图标失败")
