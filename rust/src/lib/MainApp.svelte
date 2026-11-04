<script lang="ts">
  import { onMount } from "svelte";
  import type { UnlistenFn } from "@tauri-apps/api/event";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { writeText } from "@tauri-apps/plugin-clipboard-manager";
  import { confirm, save } from "@tauri-apps/plugin-dialog";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import {
    Music2,
    Settings,
    Play,
    Square,
    RefreshCw,
    Search,
    Download,
    Copy,
    Trash2,
    EyeOff,
    RotateCcw,
    X,
    CheckCircle2,
    AlertCircle,
    HelpCircle,
    ListMusic,
    History,
    Server,
    Wifi,
    WifiOff,
    ExternalLink,
    Minus,
    ChevronDown,
    Loader2,
    Sparkles,
  } from "@lucide/svelte";

  import SettingsDialog from "./SettingsDialog.svelte";
  import {
    getSnapshot,
    startMonitoring,
    stopMonitoring,
    saveLastTab,
    recheckCurrent,
    recheckMissing,
    setMissingStatusMany,
    deleteMissingMany,
    clearHistory as clearHistoryApi,
    exportMissing as exportMissingApi,
    exportHistory as exportHistoryApi,
    onStateChanged,
    onNavigate,
    onNotificationFallback,
  } from "./api";
  import type { ActionResponse, MissingSong, NotificationItem, PlayRecord, Snapshot } from "./types";
  import {
    PLAYER_COLORS,
    SOURCE_NAMES,
    missingStatusText,
    playerName,
    playerShortName,
    recordStatus,
    recordStatusText,
    searchUrl,
    truncate,
  } from "./utils";

  type Toast = { id: number; text: string; kind: "info" | "success" | "error" };
  type ContextMenu = {
    x: number;
    y: number;
    type: "missing" | "history";
    key: string;
  };
  type SortColumn = "title" | "artist" | "player" | "first_seen" | "last_seen" | "play_count" | "status";

  let snapshot = $state<Snapshot | null>(null);
  let activeTab = $state<"missing" | "history">("missing");
  let tabInitialized = false;
  let missingSearch = $state("");
  let missingStatus = $state("pending");
  let historySearch = $state("");
  let historyStatus = $state("all");
  let selectedMissingKeys = $state<string[]>([]);
  let missingAnchorKey = $state<string | null>(null);
  let selectedHistoryKey = $state<string | null>(null);
  let settingsOpen = $state(false);
  let busy = $state(false);
  let statusMessage = $state("提示：双击复制，右键查看更多操作");
  let contextMenu = $state<ContextMenu | null>(null);
  let missingSort = $state<{ column: SortColumn; reverse: boolean }>({
    column: "first_seen",
    reverse: true,
  });
  let toasts = $state<Toast[]>([]);
  let toastSeq = 0;

  const currentRows = $derived.by(() => {
    if (!snapshot) return [];
    return ["qq", "netease"]
      .filter((key) => snapshot!.current_songs[key])
      .map((key) => ({
        key,
        song: snapshot!.current_songs[key],
        record: snapshot!.current_records[key] ?? null,
        source: snapshot!.current_sources[key] ?? "",
      }));
  });

  const historyNewest = $derived(snapshot ? [...snapshot.history].reverse() : []);

  const stats = $derived.by(() => {
    const history = snapshot?.history ?? [];
    return {
      total: history.length,
      inLibrary: history.filter((record) => record.in_library === true).length,
      pending: snapshot?.missing_count ?? 0,
      qq: history.filter((record) => record.player === "qq").length,
      netease: history.filter((record) => record.player === "netease").length,
    };
  });

  const missingFiltered = $derived.by(() => {
    if (!snapshot) return [];
    const query = missingSearch.trim().toLowerCase();
    const list = snapshot.missing.filter((entry) => {
      if (missingStatus === "pending" && entry.status !== "pending") return false;
      if (missingStatus === "ignored" && entry.status !== "ignored") return false;
      if (!query) return true;
      return `${entry.title} ${entry.artist} ${playerName(entry.player)}`.toLowerCase().includes(query);
    });
    const column = missingSort.column;
    const direction = missingSort.reverse ? -1 : 1;
    return list.sort((left, right) => {
      let a: string | number = "";
      let b: string | number = "";
      switch (column) {
        case "play_count":
          a = left.play_count;
          b = right.play_count;
          break;
        case "player":
          a = playerName(left.player);
          b = playerName(right.player);
          break;
        case "status":
          a = missingStatusText(left.status);
          b = missingStatusText(right.status);
          break;
        default:
          a = (left[column] as string) ?? "";
          b = (right[column] as string) ?? "";
      }
      if (typeof a === "number" && typeof b === "number") return (a - b) * direction;
      return String(a).localeCompare(String(b), "zh-CN") * direction;
    });
  });

  const historyFiltered = $derived.by(() => {
    if (!snapshot) return [];
    const query = historySearch.trim().toLowerCase();
    return historyNewest.filter((record) => {
      if (historyStatus === "in_library" && record.in_library !== true) return false;
      if (historyStatus === "not_in_library" && record.in_library !== false) return false;
      if (historyStatus === "unknown" && record.in_library !== null) return false;
      if (!query) return true;
      return `${record.title} ${record.artist} ${playerName(record.player)} ${recordStatusText(record)}`
        .toLowerCase()
        .includes(query);
    });
  });

  const selectedMissingEntries = $derived(
    missingFiltered.filter((entry) => selectedMissingKeys.includes(entry.key)),
  );

  const selectedMissingAllIgnored = $derived(
    selectedMissingEntries.length > 0 && selectedMissingEntries.every((entry) => entry.status !== "pending"),
  );

  const serverState = $derived.by(() => {
    if (!snapshot) return { text: "服务器：连接中…", className: "dot-idle", icon: Server };
    if (!snapshot.subsonic.configured) return { text: "服务器：未配置", className: "dot-bad", icon: WifiOff };
    if (snapshot.last_query_error) {
      return {
        text: `查询失败：${truncate(snapshot.last_query_error, 56)}`,
        className: "dot-bad",
        icon: AlertCircle,
      };
    }
    if (snapshot.query_ok) return { text: "服务器：已连接", className: "dot-ok", icon: Wifi };
    return { text: "服务器：已配置 · 等待查询", className: "dot-idle", icon: Server };
  });

  const lastQueryTime = $derived(historyNewest[0]?.timestamp ?? "—");

  function recordKey(record: PlayRecord): string {
    return `${record.timestamp}|${record.player}|${record.title}|${record.artist}`;
  }

  function applySnapshot(next: Snapshot) {
    snapshot = next;
    if (selectedMissingKeys.length > 0) {
      const existing = new Set(next.missing.map((entry) => entry.key));
      const kept = selectedMissingKeys.filter((key) => existing.has(key));
      if (kept.length !== selectedMissingKeys.length) selectedMissingKeys = kept;
      if (missingAnchorKey && !existing.has(missingAnchorKey)) missingAnchorKey = null;
    }
    if (!tabInitialized) {
      activeTab = next.settings.last_tab === 1 ? "history" : "missing";
      tabInitialized = true;
    }
  }

  function addToast(text: string, kind: Toast["kind"] = "info") {
    const id = ++toastSeq;
    toasts = [...toasts, { id, text, kind }];
    setTimeout(() => {
      toasts = toasts.filter((toast) => toast.id !== id);
    }, 3200);
  }

  function setMessage(text: string, kind: Toast["kind"] = "info") {
    statusMessage = text;
    if (kind !== "info") addToast(text, kind);
  }

  function applyAction(response: ActionResponse) {
    applySnapshot(response.snapshot);
    setMessage(response.message);
  }

  async function copy(text: string, label = "已复制") {
    if (!text.trim()) return;
    try {
      await writeText(text);
      addToast(label, "success");
    } catch (error) {
      addToast(`复制失败：${String(error)}`, "error");
    }
  }

  async function toggleMonitoring() {
    if (!snapshot) return;
    busy = true;
    try {
      const next = snapshot.running ? await stopMonitoring() : await startMonitoring();
      applySnapshot(next);
      setMessage(next.running ? "监控已启动" : "监控已停止", "success");
    } catch (error) {
      setMessage(String(error), "error");
    } finally {
      busy = false;
    }
  }

  async function switchTab(tab: "missing" | "history") {
    activeTab = tab;
    try {
      await saveLastTab(tab === "history" ? 1 : 0);
    } catch {
      /* 忽略页签保存失败 */
    }
  }

  function showAllHistory() {
    historyStatus = "all";
    historySearch = "";
    void switchTab("history");
  }

  function showHistoryFilter(status: string) {
    historyStatus = status;
    historySearch = "";
    void switchTab("history");
  }

  function showHistorySearch(query: string) {
    historyStatus = "all";
    historySearch = query;
    void switchTab("history");
  }

  function showPendingMissing() {
    missingStatus = "pending";
    missingSearch = "";
    void switchTab("missing");
  }

  async function recheckPlayer(player: string) {
    busy = true;
    setMessage(`正在核验 ${playerShortName(player)} 当前歌曲…`);
    try {
      applyAction(await recheckCurrent(player));
    } catch (error) {
      setMessage(String(error), "error");
    } finally {
      busy = false;
    }
  }

  async function recheckSelected() {
    const entries = selectedMissingEntries;
    if (entries.length === 0) {
      setMessage("请先选择待补歌曲");
      return;
    }
    if (entries.length > 20) {
      const ok = await confirm(`将对 ${entries.length} 首歌曲逐首查询曲库，是否继续？`, {
        title: "开始批量核验",
        kind: "info",
      });
      if (!ok) return;
    }
    busy = true;
    setMessage(entries.length === 1 ? `正在核验：${entries[0].title}` : `正在核验选中 ${entries.length} 首…`);
    try {
      applyAction(
        await recheckMissing(
          entries.map((entry) => entry.key),
          entries.length > 1,
        ),
      );
    } catch (error) {
      setMessage(String(error), "error");
    } finally {
      busy = false;
    }
  }

  async function recheckAllMissing() {
    if (!snapshot) return;
    const pending = snapshot.missing.filter((entry) => entry.status === "pending");
    if (pending.length === 0) {
      setMessage("待补清单为空");
      return;
    }
    if (pending.length > 20) {
      const ok = await confirm(`将对 ${pending.length} 首歌曲逐首查询曲库，是否继续？`, {
        title: "开始批量核验",
        kind: "info",
      });
      if (!ok) return;
    }
    busy = true;
    setMessage(`正在核验全部待补 ${pending.length} 首…`);
    try {
      applyAction(await recheckMissing(pending.map((entry) => entry.key), true));
    } catch (error) {
      setMessage(String(error), "error");
    } finally {
      busy = false;
    }
  }

  async function ignoreSelected() {
    const targets = selectedMissingEntries.filter((entry) => entry.status === "pending");
    if (targets.length === 0) {
      setMessage("选中的歌曲都已忽略");
      return;
    }
    try {
      applyAction(await setMissingStatusMany(targets.map((entry) => entry.key), "ignored"));
    } catch (error) {
      setMessage(String(error), "error");
    }
  }

  async function restoreSelected() {
    const targets = selectedMissingEntries.filter((entry) => entry.status !== "pending");
    if (targets.length === 0) {
      setMessage("选中的歌曲都已是待补");
      return;
    }
    try {
      applyAction(await setMissingStatusMany(targets.map((entry) => entry.key), "pending"));
    } catch (error) {
      setMessage(String(error), "error");
    }
  }

  async function deleteSelected() {
    const entries = selectedMissingEntries;
    if (entries.length === 0) {
      setMessage("请先选择待补歌曲");
      return;
    }
    const detail =
      entries.length === 1
        ? `确定从待补清单删除《${entries[0].title}》吗？`
        : `确定从待补清单删除 ${entries.length} 首歌曲吗？`;
    const ok = await confirm(`${detail}\n只会删除本地清单记录，不会删除服务器文件，且无法撤销。`, {
      title: "删除待补歌曲",
      kind: "warning",
    });
    if (!ok) return;
    try {
      applyAction(await deleteMissingMany(entries.map((entry) => entry.key)));
    } catch (error) {
      setMessage(String(error), "error");
    }
  }

  function selectMissingRow(event: MouseEvent, key: string) {
    if (event.shiftKey && missingAnchorKey) {
      const keys = missingFiltered.map((entry) => entry.key);
      const from = keys.indexOf(missingAnchorKey);
      const to = keys.indexOf(key);
      if (from >= 0 && to >= 0) {
        const [start, end] = from < to ? [from, to] : [to, from];
        const range = keys.slice(start, end + 1);
        selectedMissingKeys = event.ctrlKey || event.metaKey ? Array.from(new Set([...selectedMissingKeys, ...range])) : range;
        return;
      }
    }
    if (event.ctrlKey || event.metaKey) {
      selectedMissingKeys = selectedMissingKeys.includes(key)
        ? selectedMissingKeys.filter((item) => item !== key)
        : [...selectedMissingKeys, key];
      missingAnchorKey = key;
      return;
    }
    selectedMissingKeys = [key];
    missingAnchorKey = key;
  }

  function selectOnlyMissing(key: string) {
    selectedMissingKeys = [key];
    missingAnchorKey = key;
  }

  function handleWindowKeydown(event: KeyboardEvent) {
    if (settingsOpen || !(event.ctrlKey || event.metaKey)) return;
    const target = event.target as HTMLElement | null;
    const tag = target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) return;
    const key = event.key.toLowerCase();

    if (key === "a" && activeTab === "missing") {
      event.preventDefault();
      selectedMissingKeys = missingFiltered.map((entry) => entry.key);
      missingAnchorKey = missingFiltered[0]?.key ?? null;
      return;
    }

    if (key !== "c") return;
    if (activeTab === "missing" && selectedMissingEntries.length > 0) {
      event.preventDefault();
      copySelectedMissing();
    } else if (activeTab === "history" && selectedHistoryKey) {
      const record = historyNewest.find((item) => recordKey(item) === selectedHistoryKey);
      if (record) {
        event.preventDefault();
        copyHistoryEntry(record, true);
      }
    }
  }

  async function clearHistory() {
    if (!snapshot || snapshot.history.length === 0) {
      setMessage("没有播放记录");
      return;
    }
    const ok = await confirm("确定清空本次运行的全部播放记录吗？待补清单和服务器曲库不会受到影响。", {
      title: "清空播放记录",
      kind: "warning",
    });
    if (!ok) return;
    try {
      applySnapshot(await clearHistoryApi());
      setMessage("播放记录已清空", "success");
    } catch (error) {
      setMessage(String(error), "error");
    }
  }

  function timestampForFile(): string {
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, "0");
    return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  }

  async function exportMissing() {
    if (missingFiltered.length === 0) {
      setMessage("没有可导出的歌曲");
      return;
    }
    const path = await save({
      title: "导出待补清单",
      defaultPath: `待补歌曲_${timestampForFile()}.csv`,
      filters: [
        { name: "CSV 文件", extensions: ["csv"] },
        { name: "文本文件", extensions: ["txt"] },
      ],
    });
    if (!path) return;
    try {
      const message = await exportMissingApi(path, missingFiltered.map((entry) => entry.key));
      setMessage(message, "success");
    } catch (error) {
      setMessage(String(error), "error");
    }
  }

  async function exportHistory() {
    if (historyFiltered.length === 0) {
      setMessage("当前筛选条件下没有可导出的记录");
      return;
    }
    const path = await save({
      title: "导出播放记录",
      defaultPath: `音乐播放记录_${timestampForFile()}.csv`,
      filters: [{ name: "CSV 文件", extensions: ["csv"] }],
    });
    if (!path) return;
    try {
      const message = await exportHistoryApi(path, historyStatus, historySearch);
      setMessage(message, "success");
    } catch (error) {
      setMessage(String(error), "error");
    }
  }

  function copyCurrent(player: string, infoOnly: boolean) {
    const song = snapshot?.current_songs[player];
    if (!song) return;
    void copy(infoOnly ? `${song.title} - ${song.artist}` : song.title, infoOnly ? "已复制歌曲信息" : "已复制歌名");
  }

  function copyMissingEntry(entry: MissingSong, infoOnly: boolean) {
    void copy(infoOnly ? `${entry.title} - ${entry.artist}` : entry.title, infoOnly ? "已复制歌曲信息" : "已复制歌名");
  }

  function copyHistoryEntry(record: PlayRecord, infoOnly: boolean) {
    void copy(infoOnly ? `${record.title} - ${record.artist}` : record.title, infoOnly ? "已复制歌曲信息" : "已复制歌名");
  }

  function copySelectedMissing() {
    const entries = selectedMissingEntries;
    if (entries.length === 0) {
      setMessage("请先选择待补歌曲");
      return;
    }
    void copy(
      entries.map((entry) => `${entry.title} - ${entry.artist}`).join("\n"),
      `已复制 ${entries.length} 首歌曲信息`,
    );
  }

  function copySelectedMissingTitles() {
    const entries = selectedMissingEntries;
    if (entries.length === 0) {
      setMessage("请先选择待补歌曲");
      return;
    }
    void copy(
      entries.map((entry) => entry.title).join("\n"),
      `已复制 ${entries.length} 首歌名`,
    );
  }

  function copyAllMissing() {
    if (missingFiltered.length === 0) {
      setMessage("当前筛选条件下没有歌曲");
      return;
    }
    void copy(missingFiltered.map((entry) => `${entry.title} - ${entry.artist}`).join("\n"), `已复制 ${missingFiltered.length} 首`);
  }

  async function openSearch(player: string, query: string) {
    try {
      await openUrl(searchUrl(player, query));
    } catch (error) {
      setMessage(`打开浏览器失败：${String(error)}`, "error");
    }
  }

  function openContextMenu(event: MouseEvent, type: "missing" | "history", key: string) {
    event.preventDefault();
    const width = 230;
    const height = type === "missing" ? 340 : 230;
    contextMenu = {
      x: Math.min(event.clientX, window.innerWidth - width - 8),
      y: Math.min(event.clientY, window.innerHeight - height - 8),
      type,
      key,
    };
  }

  function contextMissing(): MissingSong | null {
    if (!snapshot || contextMenu?.type !== "missing") return null;
    return snapshot.missing.find((entry) => entry.key === contextMenu!.key) ?? null;
  }

  function contextHistory(): PlayRecord | null {
    if (!snapshot || contextMenu?.type !== "history") return null;
    return historyNewest.find((record) => recordKey(record) === contextMenu!.key) ?? null;
  }

  function toggleMissingSort(column: SortColumn) {
    if (missingSort.column === column) {
      missingSort = { column, reverse: !missingSort.reverse };
    } else {
      missingSort = { column, reverse: true };
    }
  }

  function currentStatus(record: PlayRecord | null) {
    if (!record) {
      return snapshot?.subsonic.configured
        ? { text: "查询中…", className: "chip-unknown" }
        : { text: "未配置服务器", className: "chip-unknown" };
    }
    if (record.in_library === true) return { text: "✓ 在库", className: "chip-in" };
    if (record.in_library === false) return { text: "✕ 不在库", className: "chip-missing" };
    return { text: "未知", className: "chip-unknown" };
  }

  onMount(() => {
    let disposed = false;
    const unlisteners: UnlistenFn[] = [];

    const refreshTimer = setInterval(() => {
      if (disposed) return;
      void getSnapshot()
        .then((next) => {
          if (!disposed) applySnapshot(next);
        })
        .catch(() => {
          /* 窗口关闭时忽略 */
        });
    }, 1000);

    void getSnapshot()
      .then((next) => {
        if (!disposed) applySnapshot(next);
      })
      .catch((error) => setMessage(`读取状态失败：${String(error)}`, "error"));

    onStateChanged((next) => {
      if (!disposed) applySnapshot(next);
    }).then((unlisten) => {
      if (disposed) unlisten();
      else unlisteners.push(unlisten);
    });

    onNavigate((tab) => {
      if (!disposed) void switchTab(tab === "history" ? "history" : "missing");
    }).then((unlisten) => {
      if (disposed) unlisten();
      else unlisteners.push(unlisten);
    });

    onNotificationFallback((payload) => {
      if (disposed) return;
      const item = payload as NotificationItem;
      addToast(`${item.title} - ${item.artist}`, item.status === true ? "success" : item.status === false ? "error" : "info");
    }).then((unlisten) => {
      if (disposed) unlisten();
      else unlisteners.push(unlisten);
    });

    return () => {
      disposed = true;
      clearInterval(refreshTimer);
      unlisteners.forEach((unlisten) => unlisten());
    };
  });
</script>

<svelte:window onclick={() => (contextMenu = null)} onkeydown={handleWindowKeydown} />

<div class="app-shell">
  <header class="topbar">
    <div class="brand-mark"><Music2 size={24} strokeWidth={2.2} /></div>
    <div class="min-w-0">
      <div class="brand-title">{snapshot?.app_name ?? "MelodyGap 曲库补漏"}</div>
      <div class="brand-sub">Subsonic · 每 2 秒检测与待补清单</div>
    </div>
    <div class="ml-auto flex flex-wrap items-center justify-end gap-2">
      <span class="badge-count"><ListMusic size={13} /> 待补 {snapshot?.missing_count ?? 0}</span>
      <span class="status-pill" class:ok={snapshot?.running} class:off={snapshot && !snapshot.running}>
        <span class="status-dot"></span>
        {snapshot?.running ? "监控中" : "已停止"}
      </span>
      <button class="btn btn-dark" onclick={toggleMonitoring} disabled={busy || !snapshot}>
        {#if busy}
          <Loader2 size={14} class="animate-spin" />
        {:else if snapshot?.running}
          <Square size={13} />
        {:else}
          <Play size={13} />
        {/if}
        {snapshot?.running ? "停止" : "开始"}
      </button>
      <button class="btn btn-dark" onclick={() => (settingsOpen = true)} disabled={!snapshot}>
        <Settings size={14} /> 设置
      </button>
    </div>
  </header>

  <section class="hero">
    <div class="flex items-center justify-between gap-3">
      <div class="hero-label">正在播放</div>
      <div class="flex items-center gap-2 text-[11px] text-slate-400">
        {#if snapshot?.smtc_available}
          <Sparkles size={13} class="text-cyan-300" /> SMTC 已就绪
        {:else}
          <Server size={13} /> 窗口标题回退
        {/if}
      </div>
    </div>

    {#if currentRows.length === 0}
      <div class="flex items-center gap-3 py-5">
        <div class="grid h-11 w-11 place-items-center rounded-2xl bg-white/10 text-slate-300">
          <Music2 size={20} />
        </div>
        <div>
          <div class="text-[15px] font-bold text-slate-100">暂无播放</div>
          <div class="mt-0.5 text-[12px] text-slate-400">等待 QQ音乐 / 网易云音乐开始播放</div>
        </div>
      </div>
    {:else}
      <div class="mt-1">
        {#each currentRows as row (row.key)}
          <div class="current-row">
            <span class="player-badge" style:background={PLAYER_COLORS[row.key] ?? "#4f46e5"}>
              {playerShortName(row.key)}
            </span>
            <div class="min-w-0">
              <div class="current-title" title={row.song.title}>{row.song.title}</div>
              <div class="current-meta">
                {row.song.artist || "未知歌手"} · {SOURCE_NAMES[row.source] ?? "自动检测"}
              </div>
            </div>
            <span class="current-status chip {currentStatus(row.record).className}">
              {currentStatus(row.record).text}
            </span>
            <div class="current-actions flex items-center gap-2">
              <button class="btn btn-sm btn-dark" onclick={() => copyCurrent(row.key, false)}>
                <Copy size={12} /> 歌名
              </button>
              <button class="btn btn-sm btn-dark" onclick={() => copyCurrent(row.key, true)}>
                信息
              </button>
              {#if row.record?.in_library !== true}
                <button class="btn btn-sm btn-white" onclick={() => recheckPlayer(row.key)} disabled={busy}>
                  <RefreshCw size={12} /> 重新查询
                </button>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <section class="stat-grid">
    <button class="stat-card" style="--accent: #4f46e5" onclick={() => showAllHistory()}>
      <div class="stat-value">{stats.total}</div>
      <div class="stat-label">播放记录</div>
    </button>
    <button class="stat-card" style="--accent: #10b981" onclick={() => showHistoryFilter("in_library")}>
      <div class="stat-value text-emerald-600">{stats.inLibrary}</div>
      <div class="stat-label">在曲库</div>
    </button>
    <button class="stat-card" style="--accent: #f59e0b" onclick={() => showPendingMissing()}>
      <div class="stat-value text-amber-600">{stats.pending}</div>
      <div class="stat-label">待补歌曲</div>
    </button>
    <button class="stat-card" style="--accent: #2563eb" onclick={() => showHistorySearch("QQ音乐")}>
      <div class="stat-value text-blue-600">{stats.qq}</div>
      <div class="stat-label">QQ音乐</div>
    </button>
    <button class="stat-card" style="--accent: #dc2626" onclick={() => showHistorySearch("网易云")}>
      <div class="stat-value text-red-600">{stats.netease}</div>
      <div class="stat-label">网易云音乐</div>
    </button>
  </section>

  <section class="panel">
    <div class="tabs">
      <button class="tab" class:active={activeTab === "missing"} onclick={() => switchTab("missing")}>
        <ListMusic size={15} /> 待补清单
        <span class="tab-count">{missingFiltered.length}</span>
      </button>
      <button class="tab" class:active={activeTab === "history"} onclick={() => switchTab("history")}>
        <History size={15} /> 播放记录
        <span class="tab-count">{historyFiltered.length}</span>
      </button>
      <div class="ml-auto flex items-center gap-2 text-[11px] text-slate-400">
        <ChevronDown size={13} />
        双击复制 · 右键更多操作
      </div>
    </div>

    {#if activeTab === "missing"}
      <div class="toolbar">
        <div class="relative">
          <Search size={14} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input class="input w-[210px] pl-8" placeholder="搜索歌名 / 歌手 / 播放器" bind:value={missingSearch} />
        </div>
        <select class="select" bind:value={missingStatus}>
          <option value="pending">待补</option>
          <option value="ignored">已忽略</option>
          <option value="all">全部</option>
        </select>
        <div class="mx-1 h-5 w-px bg-slate-200"></div>
        <button class="btn btn-soft" onclick={copySelectedMissing} disabled={selectedMissingEntries.length === 0}>
          <Copy size={13} /> 复制选中
        </button>
        <button class="btn btn-ghost" onclick={copyAllMissing}>
          <Copy size={13} /> 复制列表
        </button>
        <button class="btn btn-success" onclick={exportMissing}>
          <Download size={13} /> 导出
        </button>
        <button class="btn btn-primary" onclick={recheckSelected} disabled={busy || selectedMissingEntries.length === 0}>
          <RefreshCw size={13} /> 核验选中
        </button>
        <button class="btn btn-ghost" onclick={recheckAllMissing} disabled={busy || stats.pending === 0}>
          <RotateCcw size={13} /> 核验待补
        </button>
        {#if selectedMissingAllIgnored}
          <button class="btn btn-ghost" onclick={restoreSelected}>
            <RotateCcw size={13} /> 恢复待补
          </button>
        {:else}
          <button class="btn btn-ghost" onclick={ignoreSelected} disabled={selectedMissingEntries.length === 0}>
            <EyeOff size={13} /> 忽略
          </button>
        {/if}
        <button class="btn btn-danger" onclick={deleteSelected} disabled={selectedMissingEntries.length === 0}>
          <Trash2 size={13} /> 删除
        </button>
        <div class="ml-auto text-[11px] font-semibold text-slate-400">{missingFiltered.length} 首</div>
      </div>

      <div class="table-wrap">
        {#if missingFiltered.length === 0}
          <div class="empty">
            <div class="empty-icon"><CheckCircle2 size={20} /></div>
            <div class="text-[13px] font-semibold text-slate-600">
              {snapshot?.missing.length ? "当前筛选条件下没有歌曲" : "待补清单为空"}
            </div>
            <div class="text-[11.5px]">播放不在曲库中的歌曲后会自动加入这里</div>
          </div>
        {:else}
          <table class="data">
            <thead>
              <tr>
                <th class="cursor-pointer" onclick={() => toggleMissingSort("title")}>歌曲名称</th>
                <th class="cursor-pointer" onclick={() => toggleMissingSort("artist")}>歌手</th>
                <th class="cursor-pointer" onclick={() => toggleMissingSort("player")}>播放器</th>
                <th class="cursor-pointer" onclick={() => toggleMissingSort("first_seen")}>首次发现</th>
                <th class="cursor-pointer" onclick={() => toggleMissingSort("last_seen")}>最后发现</th>
                <th class="cursor-pointer" onclick={() => toggleMissingSort("play_count")}>次数</th>
                <th class="cursor-pointer" onclick={() => toggleMissingSort("status")}>状态</th>
              </tr>
            </thead>
            <tbody>
              {#each missingFiltered as entry (entry.key)}
                <tr
                  class:selected={selectedMissingKeys.includes(entry.key)}
                  onclick={(event) => selectMissingRow(event, entry.key)}
                  ondblclick={() => copyMissingEntry(entry, true)}
                  oncontextmenu={(event) => {
                    if (!selectedMissingKeys.includes(entry.key)) selectOnlyMissing(entry.key);
                    openContextMenu(event, "missing", entry.key);
                  }}
                >
                  <td><div class="cell-title" title={entry.title}>{entry.title}</div></td>
                  <td class="cell-muted">{entry.artist || "—"}</td>
                  <td class="cell-muted">
                    <span class="player-dot" style:background={PLAYER_COLORS[entry.player] ?? "#94a3b8"}></span>
                    {playerShortName(entry.player)}
                  </td>
                  <td class="cell-mono">{entry.first_seen}</td>
                  <td class="cell-mono">{entry.last_seen}</td>
                  <td class="cell-mono">{entry.play_count}</td>
                  <td>
                    <span class="chip" class:chip-pending={entry.status === "pending"} class:chip-ignored={entry.status !== "pending"}>
                      {missingStatusText(entry.status)}
                    </span>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
    {:else}
      <div class="toolbar">
        <div class="relative">
          <Search size={14} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input class="input w-[210px] pl-8" placeholder="搜索歌名 / 歌手 / 状态" bind:value={historySearch} />
        </div>
        <select class="select" bind:value={historyStatus}>
          <option value="all">全部</option>
          <option value="in_library">在库</option>
          <option value="not_in_library">不在库</option>
          <option value="unknown">未知</option>
        </select>
        <div class="mx-1 h-5 w-px bg-slate-200"></div>
        <button class="btn btn-success" onclick={exportHistory}>
          <Download size={13} /> 导出
        </button>
        <button class="btn btn-danger" onclick={clearHistory}>
          <Trash2 size={13} /> 清空
        </button>
        <div class="ml-auto text-[11px] font-semibold text-slate-400">{historyFiltered.length} 条</div>
      </div>

      <div class="table-wrap">
        {#if historyFiltered.length === 0}
          <div class="empty">
            <div class="empty-icon"><History size={20} /></div>
            <div class="text-[13px] font-semibold text-slate-600">暂无播放记录</div>
            <div class="text-[11.5px]">检测到歌曲切换后会记录在这里</div>
          </div>
        {:else}
          <table class="data">
            <thead>
              <tr>
                <th>播放时间</th>
                <th>歌曲名称</th>
                <th>歌手</th>
                <th>播放器</th>
                <th>曲库状态</th>
              </tr>
            </thead>
            <tbody>
              {#each historyFiltered as record (recordKey(record))}
                <tr
                  class:selected={selectedHistoryKey === recordKey(record)}
                  onclick={() => (selectedHistoryKey = recordKey(record))}
                  ondblclick={() => copyHistoryEntry(record, true)}
                  oncontextmenu={(event) => openContextMenu(event, "history", recordKey(record))}
                >
                  <td class="cell-mono">{record.timestamp}</td>
                  <td><div class="cell-title" title={record.title}>{record.title}</div></td>
                  <td class="cell-muted">{record.artist || "—"}</td>
                  <td class="cell-muted">
                    <span class="player-dot" style:background={PLAYER_COLORS[record.player] ?? "#94a3b8"}></span>
                    {playerShortName(record.player)}
                  </td>
                  <td>
                    <span
                      class="chip"
                      class:chip-in={recordStatus(record) === "in_library"}
                      class:chip-missing={recordStatus(record) === "not_in_library"}
                      class:chip-unknown={recordStatus(record) === "unknown"}
                    >
                      {recordStatusText(record)}
                    </span>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
    {/if}

    <div class="footer">
      <span class="inline-flex items-center gap-1.5 {serverState.className}">
        {#if !snapshot?.subsonic.configured}
          <WifiOff size={13} />
        {:else if snapshot?.last_query_error}
          <AlertCircle size={13} />
        {:else if snapshot?.query_ok}
          <Wifi size={13} />
        {:else}
          <Server size={13} />
        {/if}
        {serverState.text}
      </span>
      <span>最后查询：{lastQueryTime}</span>
      <span class="font-semibold text-indigo-600">{statusMessage}</span>
      <span class="spacer"></span>
      <span class="text-slate-400">v{snapshot?.app_version ?? "2.0.0"}</span>
      <button class="btn btn-sm btn-ghost" onclick={() => (settingsOpen = true)} disabled={!snapshot}>
        <Settings size={13} /> 设置
      </button>
      <button class="btn btn-sm btn-ghost" onclick={() => void getCurrentWindow().hide()}>
        <Minus size={13} /> 最小化
      </button>
    </div>
  </section>
</div>

{#if settingsOpen && snapshot}
  <SettingsDialog
    {snapshot}
    onclose={() => (settingsOpen = false)}
    onsaved={(response) => applyAction(response)}
    onmessage={(message, kind) => setMessage(message, kind ?? "info")}
  />
{/if}

{#if contextMenu}
  <div
    class="context-menu"
    style:left={`${contextMenu.x}px`}
    style:top={`${contextMenu.y}px`}
    onclick={(event) => event.stopPropagation()}
    onkeydown={(event) => event.stopPropagation()}
    role="menu"
    tabindex="-1"
  >
    {#if contextMenu.type === "missing" && contextMissing()}
      {@const entry = contextMissing()!}
      <button
        role="menuitem"
        onclick={() => {
          copySelectedMissingTitles();
          contextMenu = null;
        }}
      >
        <Copy size={13} />
        {selectedMissingEntries.length > 1 ? `复制 ${selectedMissingEntries.length} 首歌名` : "复制歌名"}
      </button>
      <button
        role="menuitem"
        onclick={() => {
          copySelectedMissing();
          contextMenu = null;
        }}
      >
        <Copy size={13} />
        {selectedMissingEntries.length > 1 ? `复制 ${selectedMissingEntries.length} 首歌曲信息` : "复制歌曲信息"}
      </button>
      <div class="separator"></div>
      <button
        role="menuitem"
        onclick={() => {
          void openSearch("qq", `${entry.title} ${entry.artist}`);
          contextMenu = null;
        }}
      >
        <ExternalLink size={13} /> 在 QQ 音乐搜索
      </button>
      <button
        role="menuitem"
        onclick={() => {
          void openSearch("netease", `${entry.title} ${entry.artist}`);
          contextMenu = null;
        }}
      >
        <ExternalLink size={13} /> 在网易云搜索
      </button>
      <div class="separator"></div>
      <button
        role="menuitem"
        onclick={() => {
          void recheckSelected();
          contextMenu = null;
        }}
      >
        <RefreshCw size={13} />
        {selectedMissingEntries.length > 1 ? `核验选中 ${selectedMissingEntries.length} 首` : "核验这首歌"}
      </button>
      <button
        role="menuitem"
        onclick={() => {
          if (selectedMissingAllIgnored) void restoreSelected();
          else void ignoreSelected();
          contextMenu = null;
        }}
      >
        {#if selectedMissingAllIgnored}
          <RotateCcw size={13} /> 恢复待补
        {:else}
          <EyeOff size={13} /> 忽略
        {/if}
      </button>
      <button
        class="danger"
        role="menuitem"
        onclick={() => {
          void deleteSelected();
          contextMenu = null;
        }}
      >
        <Trash2 size={13} />
        {selectedMissingEntries.length > 1 ? `删除选中 ${selectedMissingEntries.length} 首` : "删除"}
      </button>
    {:else if contextMenu.type === "history" && contextHistory()}
      {@const record = contextHistory()!}
      <button
        role="menuitem"
        onclick={() => {
          copyHistoryEntry(record, false);
          contextMenu = null;
        }}
      >
        <Copy size={13} /> 复制歌名
      </button>
      <button
        role="menuitem"
        onclick={() => {
          copyHistoryEntry(record, true);
          contextMenu = null;
        }}
      >
        <Copy size={13} /> 复制歌曲信息
      </button>
      <div class="separator"></div>
      <button
        role="menuitem"
        onclick={() => {
          void openSearch("qq", `${record.title} ${record.artist}`);
          contextMenu = null;
        }}
      >
        <ExternalLink size={13} /> 在 QQ 音乐搜索
      </button>
      <button
        role="menuitem"
        onclick={() => {
          void openSearch("netease", `${record.title} ${record.artist}`);
          contextMenu = null;
        }}
      >
        <ExternalLink size={13} /> 在网易云搜索
      </button>
    {/if}
  </div>
{/if}

<div class="toast-stack">
  {#each toasts as toast (toast.id)}
    <div class="toast {toast.kind}">
      {#if toast.kind === "success"}
        <CheckCircle2 size={15} class="mt-0.5 flex-none" />
      {:else if toast.kind === "error"}
        <AlertCircle size={15} class="mt-0.5 flex-none" />
      {:else}
        <HelpCircle size={15} class="mt-0.5 flex-none" />
      {/if}
      <span>{toast.text}</span>
    </div>
  {/each}
</div>
