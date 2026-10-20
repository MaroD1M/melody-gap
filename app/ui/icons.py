# -*- coding: utf-8 -*-
"""图标生成与加载。

旧版在设置窗口、主窗口、托盘三处各复制了一份“画蓝色圆圈 + 音符”的代码，
本模块统一实现，并提供 ``icon.ico`` 优先、动态绘制兜底的加载策略。
"""

import base64
import io
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from app.constants import ICON_FILE_NAME
from app.paths import get_resource_path

logger = logging.getLogger(__name__)

_ICON_BG = "#0078D4"
_ICON_BORDER = "#005A9E"


def _load_font(size: int):
    """尝试加载常见字体，失败时回退到 Pillow 内置字体。"""
    candidates = (
        "arial.ttf",
        "segoeui.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def create_music_icon(size: int = 64) -> Image.Image:
    """动态绘制音符图标（托盘/窗口兜底图标）。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    padding = max(1, size // 8)
    border = max(1, size // 21)
    draw.ellipse(
        [padding, padding, size - padding, size - padding],
        fill=_ICON_BG,
        outline=_ICON_BORDER,
        width=border,
    )

    font = _load_font(max(10, int(size * 0.45)))
    glyph = "♪"
    try:
        if font is not None:
            bbox = draw.textbbox((0, 0), glyph, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            draw.text(
                ((size - text_width) / 2 - bbox[0], (size - text_height) / 2 - bbox[1]),
                glyph,
                fill="white",
                font=font,
            )
            return image
    except Exception:
        pass

    # 字体不可用/字形缺失：用几何图形画一个简单音符
    cx = size * 0.42
    cy = size * 0.62
    head_r = size * 0.11
    draw.ellipse([cx - head_r, cy - head_r, cx + head_r, cy + head_r], fill="white")
    draw.rectangle([cx + head_r * 0.45, size * 0.30, cx + head_r * 1.15, cy], fill="white")
    draw.ellipse(
        [cx + head_r * 0.0, size * 0.26, cx + head_r * 1.6, size * 0.40],
        fill="white",
    )
    return image


def load_window_icon(widget) -> Optional[object]:
    """为 Tk 窗口设置图标。

    优先读取打包/项目目录下的 ``icon.ico``；失败则动态绘制。
    返回 ``PhotoImage``，调用方需保留引用防止被垃圾回收。
    """
    import tkinter as tk

    image: Optional[Image.Image] = None
    icon_path: Path = get_resource_path(ICON_FILE_NAME)
    if icon_path.exists():
        try:
            with Image.open(icon_path) as ico:
                image = ico.convert("RGBA").resize((32, 32), Image.LANCZOS)
        except Exception as exc:
            logger.debug("加载 %s 失败，使用动态图标: %s", icon_path, exc)

    if image is None:
        image = create_music_icon(32)

    try:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        photo = tk.PhotoImage(data=encoded)
        widget.iconphoto(True, photo)
        return photo
    except Exception as exc:
        logger.debug("设置窗口图标失败: %s", exc)
        return None


def create_tray_image(size: int = 64) -> Image.Image:
    """托盘图标；优先加载 icon.ico 以保持与 exe 图标一致。"""
    icon_path: Path = get_resource_path(ICON_FILE_NAME)
    if icon_path.exists():
        try:
            with Image.open(icon_path) as ico:
                return ico.convert("RGBA").resize((size, size), Image.LANCZOS)
        except Exception as exc:
            logger.debug("加载托盘图标失败，使用动态图标: %s", exc)
    return create_music_icon(size)
