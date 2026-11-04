export type SongInfo = {
  title: string;
  artist: string;
  player: string;
};

export type PlayRecord = {
  timestamp: string;
  title: string;
  artist: string;
  in_library: boolean | null;
  full_title: string;
  player: string;
};

export type MissingSong = {
  key: string;
  title: string;
  artist: string;
  player: string;
  first_seen: string;
  last_seen: string;
  play_count: number;
  status: string;
};

export type SettingsView = {
  reminder_mode: string;
  reminder_cooldown_minutes: number;
  window_geometry: string;
  window_zoomed: boolean;
  last_tab: number;
};

export type SubsonicView = {
  server_url: string;
  username: string;
  verify_ssl: boolean;
  password_set: boolean;
  configured: boolean;
};

export type Snapshot = {
  app_name: string;
  app_version: string;
  running: boolean;
  current_songs: Record<string, SongInfo>;
  current_records: Record<string, PlayRecord>;
  current_sources: Record<string, string>;
  history: PlayRecord[];
  missing: MissingSong[];
  settings: SettingsView;
  subsonic: SubsonicView;
  query_ok: boolean;
  last_query_error: string | null;
  missing_count: number;
  smtc_available: boolean;
  smtc_error: string | null;
};

export type ActionResponse = {
  message: string;
  snapshot: Snapshot;
};

export type TestResponse = {
  ok: boolean;
  message: string;
  server_type: string;
  server_version: string;
  api_version: string;
};

export type NotificationItem = {
  id: number;
  title: string;
  artist: string;
  status: boolean | null;
  player: string;
  player_name: string;
  is_new_missing: boolean;
  copy_text: string;
};

export type SettingsPayload = {
  server_url: string;
  username: string;
  password: string;
  verify_ssl: boolean;
  reminder_mode: string;
  reminder_cooldown_minutes: number;
  last_tab: number;
  clear_password: boolean;
};

export type ConnectionPayload = {
  server_url: string;
  username: string;
  password: string;
  verify_ssl: boolean;
};
