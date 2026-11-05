import type { PlayRecord } from "./types";

const PLAYER_NAMES: Record<string, string> = {
  qq: "QQ音乐",
  netease: "网易云音乐",
};

const PLAYER_SHORT_NAMES: Record<string, string> = {
  qq: "QQ音乐",
  netease: "网易云",
};

export const PLAYER_COLORS: Record<string, string> = {
  qq: "#2563eb",
  netease: "#dc2626",
};

export const SOURCE_NAMES: Record<string, string> = {
  smtc: "系统媒体会话",
  window: "窗口标题",
};

export function playerName(key: string): string {
  return PLAYER_NAMES[key] ?? key;
}

export function playerShortName(key: string): string {
  return PLAYER_SHORT_NAMES[key] ?? key;
}

export function recordStatus(record: PlayRecord): "in_library" | "not_in_library" | "unknown" {
  if (record.in_library === true) return "in_library";
  if (record.in_library === false) return "not_in_library";
  return "unknown";
}

export function recordStatusText(record: PlayRecord): string {
  if (record.in_library === true) return "在曲库";
  if (record.in_library === false) return "不在库";
  return "未知";
}

export function missingStatusText(status: string): string {
  return status === "ignored" ? "已忽略" : "待补";
}

export function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 3)}...`;
}

export function searchUrl(player: string, query: string): string {
  const encoded = encodeURIComponent(query);
  if (player === "qq") {
    return `https://y.qq.com/n/ryqq/search?w=${encoded}`;
  }
  return `https://music.163.com/#/search/m/?s=${encoded}&type=1`;
}
