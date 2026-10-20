# -*- coding: utf-8 -*-
"""提醒策略（纯逻辑，便于单测）。

提醒只在主线程根据配置判断；本模块不依赖 Tk、网络或系统时间。
"""

from datetime import datetime, timedelta
from typing import Optional

from app.constants import (
    REMINDER_MODE_ALL,
    REMINDER_MODE_MISSING,
    REMINDER_MODE_NEW_MISSING,
    REMINDER_MODE_OFF,
)


def should_notify(
    mode: str,
    in_library: Optional[bool],
    is_new_missing: bool,
    last_notified_at: Optional[datetime],
    now: datetime,
    cooldown_minutes: int,
) -> bool:
    """判断一条播放记录是否应弹出通知。

    Args:
        mode: ``new_missing`` / ``missing`` / ``all`` / ``off``
        in_library: True 在库、False 不在库、None 查询失败
        is_new_missing: 本次是否新加入待补清单
        last_notified_at: 同一首歌上次提醒时间
        now: 当前时间
        cooldown_minutes: 冷却分钟数；仅对非“新缺失”模式生效

    Returns:
        是否显示通知。未知状态默认不提醒，避免网络故障时反复弹窗。
    """
    if in_library is None or mode == REMINDER_MODE_OFF:
        return False

    if mode == REMINDER_MODE_NEW_MISSING:
        return in_library is False and is_new_missing

    if last_notified_at is not None:
        cooldown = timedelta(minutes=max(0, cooldown_minutes))
        if now - last_notified_at < cooldown:
            return False

    if mode == REMINDER_MODE_MISSING:
        return in_library is False

    if mode == REMINDER_MODE_ALL:
        return True

    # 配置值异常时退回更保守的默认策略
    return in_library is False and is_new_missing
