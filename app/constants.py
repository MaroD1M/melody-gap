# -*- coding: utf-8 -*-
"""全局常量集中定义。

本模块不导入任何第三方库，可被所有层安全引用。修改业务参数（例如匹配
阈值、轮询间隔）时优先改这里，不要在业务代码里写魔法数字。
"""

from typing import Dict, Tuple

# ============================================================
# 应用元信息
# ============================================================

APP_NAME = "MelodyGap"                    # 单实例锁、日志、PyInstaller 名称
APP_DISPLAY_NAME = "MelodyGap 曲库补漏"    # 界面显示名称
APP_VERSION = "1.0.0"
APP_TITLE = f"{APP_DISPLAY_NAME} v{APP_VERSION}"

# 运行期文件名（均位于 get_app_dir() 目录）
CONFIG_FILE_NAME = "config.ini"
LOG_FILE_NAME = "melodygap.log"
MISSING_FILE_NAME = "missing_songs.json"
ICON_FILE_NAME = "icon.ico"

# ============================================================
# 播放器配置
# ============================================================
# key: 内部标识；processes: 可能的进程名（统一小写比较）；
# display_name: 界面显示；short_name: 通知/表格里的紧凑名称
SUPPORTED_PLAYERS: Dict[str, Dict[str, object]] = {
    "qq": {
        "processes": ("qqmusic.exe",),
        "display_name": "QQ音乐",
        "short_name": "QQ音乐",
    },
    "netease": {
        "processes": (
            "cloudmusic.exe",
            "neteasecloudmusic.exe",
            "neteasemusic.exe",
        ),
        "display_name": "网易云音乐",
        "short_name": "网易云",
    },
}

# 由 SUPPORTED_PLAYERS 派生，避免在 UI 中重复写映射表
PLAYER_DISPLAY_NAMES = {
    key: str(info["display_name"]) for key, info in SUPPORTED_PLAYERS.items()
}
PLAYER_SHORT_NAMES = {
    key: str(info["short_name"]) for key, info in SUPPORTED_PLAYERS.items()
}

# 播放器主题色（表格/统计卡片）
PLAYER_COLORS = {
    "qq": "#2563EB",
    "netease": "#DC2626",
}

# 窗口标题中出现即判定为“非歌曲标题”的通用关键词
# 功能页标题关键词：仅当某个“分隔段”与关键词完全相等时才排除。
# 不使用子串匹配，避免误杀《我的天空》《发现》这类合法歌名。
EXCLUDED_TITLE_KEYWORDS: Tuple[str, ...] = (
    "设置", "搜索", "登录", "选项", "偏好", "关于", "帮助", "更新",
    "歌单", "我的歌单", "我的音乐", "我的收藏", "播放列表", "本地音乐",
    "下载管理", "发现音乐", "每日推荐", "私人漫游", "云盘", "历史记录",
)

# 各播放器的额外排除关键词（窗口主界面标题）
PLAYER_EXCLUDED_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "qq": ("QQ音乐", "QQMusic"),
    "netease": ("网易云音乐", "NetEase", "CloudMusic"),
}

# 播放器附加在窗口标题末尾的应用名，解析前先剥离。
# 例："晴天 - 周杰伦 - 网易云音乐" -> "晴天 - 周杰伦"
PLAYER_TITLE_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "qq": ("QQ音乐", "QQMusic"),
    "netease": ("网易云音乐", "网易云", "NetEase", "NetEase Cloud Music", "CloudMusic"),
}

# 窗口标题中用于分隔“歌名 / 歌手”的符号，按优先级排列。
# 注意：不使用中文冒号，因为歌名本身常含冒号（如 "Love Story: Part 2"）；
# 且必须与 TITLE_PATTERNS 保持一致，避免“能通过校验却解析失败”。
TITLE_SEPARATORS: Tuple[str, ...] = (" - ", " — ", " – ", " | ")

# 标题解析正则：惰性匹配第一个分隔符，剩余部分视为歌手
# 例："晴天 - 周杰伦" -> ("晴天", "周杰伦")
TITLE_PATTERNS: Tuple[str, ...] = (
    r"^(.+?)\s*-\s*(.+?)$",
    r"^(.+?)\s*—\s*(.+?)$",
    r"^(.+?)\s*–\s*(.+?)$",
    r"^(.+?)\s*\|\s*(.+?)$",
)

# ============================================================
# Subsonic 接口参数
# ============================================================

SUBSONIC_API_VERSION = "1.16.1"           # 兼容性最好的通用版本
SUBSONIC_CLIENT_NAME = "MelodyGap"
SUBSONIC_REQUEST_TIMEOUT = 10             # 单次 HTTP 超时（秒）
SUBSONIC_SONG_COUNT_FULL = 50             # 完整搜索返回上限
SUBSONIC_SONG_COUNT_SINGLE = 30           # 单条件搜索返回上限
SUBSONIC_PLACEHOLDER_SERVER = "https://your-server.com"  # 默认占位地址前缀
SUBSONIC_SECTION = "SUBSONIC"             # config.ini 段名
APP_SECTION = "APP"                       # config.ini 应用设置段名

# ============================================================
# 歌曲匹配参数
# ============================================================

MATCH_THRESHOLD = 0.75        # 综合评分 >= 该值视为“在曲库中”
EARLY_STOP_SCORE = 0.90       # 首个查询达到该分数时跳过后续兜底搜索
ARTIST_WEIGHT = 0.4           # 歌手相似度权重
TITLE_WEIGHT = 0.6            # 歌名相似度权重（歌名唯一性更强）

SUBSTRING_MIN_LENGTH = 4      # 触发“子串加分”的最短字符串长度
SUBSTRING_SCORE = 0.8         # 子串关系的最低相似度

# 英文修饰词：使用单词边界匹配，避免破坏 Olive/Deliver 等正常单词
MODIFIER_WORDS_EN: Tuple[str, ...] = (
    "remix", "remaster", "remastered", "acoustic", "live", "demo",
    "instrumental", "cover", "feat", "ft", "featuring",
)

# 中文修饰词：直接替换
MODIFIER_WORDS_ZH: Tuple[str, ...] = (
    "重制版", "混音版", "伴奏", "现场版",
)

# ============================================================
# 监控 / 刷新参数
# ============================================================

MONITOR_INTERVAL_SECONDS = 2.0    # 监控轮询间隔
PROCESS_CACHE_TTL_SECONDS = 5.0   # 进程列表缓存有效期
MONITOR_STOP_TIMEOUT = 3.0        # 停止监控线程时等待上限
UI_REFRESH_INTERVAL_MS = 1000     # 主窗口自动刷新间隔

# 查询失败时自动重试。避免一次瞬时网络错误把歌曲永久标成“未知”。
UNKNOWN_RETRY_SECONDS = 15.0      # 首次失败后等待多久再试
UNKNOWN_RETRY_MAX = 5             # 同一首歌最多自动重试次数

# ============================================================
# 通知窗口参数
# ============================================================

NOTIFICATION_WIDTH = 420
NOTIFICATION_HEIGHT = 150
NOTIFICATION_MARGIN_RIGHT = 30
NOTIFICATION_MARGIN_BOTTOM = 80       # 预留任务栏高度
NOTIFICATION_DURATION_MS = 6000
NOTIFICATION_ALPHA = 0.95
NOTIFICATION_TITLE_MAX = 38
NOTIFICATION_ARTIST_MAX = 44

# ============================================================
# 待补清单
# ============================================================

MISSING_STATUS_PENDING = "pending"
MISSING_STATUS_IGNORED = "ignored"
MISSING_STATUS_LABELS = {
    MISSING_STATUS_PENDING: "待补",
    MISSING_STATUS_IGNORED: "已忽略",
}
MISSING_EXPORT_HEADERS = (
    "歌曲名称", "歌手", "播放器", "首次发现", "最后发现", "发现次数", "状态",
)

# ============================================================
# 提醒 / 界面设置
# ============================================================

REMINDER_MODE_NEW_MISSING = "new_missing"
REMINDER_MODE_MISSING = "missing"
REMINDER_MODE_ALL = "all"
REMINDER_MODE_OFF = "off"
REMINDER_MODE_LABELS = {
    REMINDER_MODE_NEW_MISSING: "仅新缺失歌曲",
    REMINDER_MODE_MISSING: "所有缺失歌曲",
    REMINDER_MODE_ALL: "全部歌曲",
    REMINDER_MODE_OFF: "关闭提醒",
}
DEFAULT_REMINDER_MODE = REMINDER_MODE_NEW_MISSING
DEFAULT_REMINDER_COOLDOWN_MINUTES = 10

DEFAULT_WINDOW_GEOMETRY = "1080x760"
DEFAULT_LAST_TAB = 0


def player_display_name(player_key: str) -> str:
    """返回播放器完整名称；未知标识原样返回。"""
    return PLAYER_DISPLAY_NAMES.get(player_key, player_key)


def player_short_name(player_key: str) -> str:
    """返回播放器紧凑名称；未知标识原样返回。"""
    return PLAYER_SHORT_NAMES.get(player_key, player_key)
