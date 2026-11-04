import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  ActionResponse,
  ConnectionPayload,
  NotificationItem,
  SettingsPayload,
  Snapshot,
  TestResponse,
} from "./types";

export const getSnapshot = () => invoke<Snapshot>("get_snapshot");
export const startMonitoring = () => invoke<Snapshot>("start_monitoring");
export const stopMonitoring = () => invoke<Snapshot>("stop_monitoring");
export const saveLastTab = (tab: number) => invoke<Snapshot>("save_last_tab", { tab });
export const saveSettings = (payload: SettingsPayload) =>
  invoke<ActionResponse>("save_settings", { payload });
export const testConnection = (payload: ConnectionPayload) =>
  invoke<TestResponse>("test_connection", { payload });
export const recheckCurrent = (player?: string) =>
  invoke<ActionResponse>("recheck_current", { player: player ?? null });
export const recheckMissing = (keys?: string[], quiet = false) =>
  invoke<ActionResponse>("recheck_missing", { keys: keys ?? null, quiet });
export const setMissingStatus = (key: string, status: string) =>
  invoke<ActionResponse>("set_missing_status", { key, status });
export const deleteMissing = (key: string) =>
  invoke<ActionResponse>("delete_missing", { key });
export const setMissingStatusMany = (keys: string[], status: string) =>
  invoke<ActionResponse>("set_missing_status_many", { keys, status });
export const deleteMissingMany = (keys: string[]) =>
  invoke<ActionResponse>("delete_missing_many", { keys });
export const clearHistory = () => invoke<Snapshot>("clear_history");
export const getCurrentNotification = () =>
  invoke<NotificationItem | null>("get_current_notification");
export const dismissNotification = (id?: number) =>
  invoke<void>("dismiss_notification", { id: id ?? null });
export const exportMissing = (path: string, keys: string[]) =>
  invoke<string>("export_missing", { path, keys });
export const exportHistory = (path: string, status: string, search: string) =>
  invoke<string>("export_history", { path, status, search });

export const onStateChanged = (handler: (snapshot: Snapshot) => void): Promise<UnlistenFn> =>
  listen<Snapshot>("state-changed", (event) => handler(event.payload));

export const onNavigate = (handler: (tab: string) => void): Promise<UnlistenFn> =>
  listen<string>("navigate", (event) => handler(event.payload));

export const onNotificationFallback = (handler: (payload: unknown) => void): Promise<UnlistenFn> =>
  listen("notification-fallback", (event) => handler(event.payload));
