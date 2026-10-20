# -*- coding: utf-8 -*-
"""跨平台单实例锁。

实现方式：对临时目录下的锁文件加**操作系统级文件锁**。

* Windows：``msvcrt.locking``（非阻塞独占锁）
* Linux/macOS：``fcntl.flock``（非阻塞独占锁）

相比旧版“扫描进程命令行里是否包含 __file__”的做法：
1. 打包成 exe 后仍然有效；
2. 进程异常退出时由操作系统自动释放锁，不会残留死锁；
3. 不需要遍历系统进程，启动更快。
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, TextIO

logger = logging.getLogger(__name__)


class SingleInstanceLock:
    """基于锁文件的单实例控制。

    用法::

        lock = SingleInstanceLock("MyApp")
        if not lock.acquire():
            print("程序已在运行")
            return
        try:
            run()
        finally:
            lock.release()

    注意：锁文件本身可以长期存在，是否“正在运行”由文件锁状态决定。
    """

    def __init__(self, name: str) -> None:
        self.path = Path(tempfile.gettempdir()) / f"{name}.lock"
        self._file: Optional[TextIO] = None
        self._acquired = False

    def acquire(self) -> bool:
        """尝试获取锁；成功返回 True，已被占用返回 False。"""
        if self._acquired:
            return True

        fp: Optional[TextIO] = None
        try:
            fp = self.path.open("a+", encoding="utf-8")
            # 某些平台要求锁区域存在，先写入 1 字节再回到开头
            fp.seek(0)
            if fp.read(1) == "":
                fp.write("0")
                fp.flush()
            fp.seek(0)

            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # 记录当前 PID，便于人工排查（锁本身不依赖 PID）
            fp.seek(0)
            fp.truncate()
            fp.write(str(os.getpid()))
            fp.flush()

            self._file = fp
            self._acquired = True
            return True

        except OSError:
            if fp is not None:
                try:
                    fp.close()
                except Exception:
                    pass
            logger.info("另一个实例已持有锁: %s", self.path)
            return False

    def release(self) -> None:
        """释放锁并关闭文件句柄。"""
        if not self._acquired or self._file is None:
            return

        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            logger.debug("释放单实例锁失败（进程退出时系统会自动释放）: %s", exc)
        finally:
            try:
                self._file.close()
            finally:
                self._file = None
                self._acquired = False
