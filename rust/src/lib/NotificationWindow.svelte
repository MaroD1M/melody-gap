<script lang="ts">
  import { onMount } from "svelte";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import { writeText } from "@tauri-apps/plugin-clipboard-manager";
  import { dismissNotification, getCurrentNotification } from "./api";
  import type { NotificationItem } from "./types";

  let item = $state<NotificationItem | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let unlisten: UnlistenFn | null = null;

  const accent = $derived(
    item?.status === true
      ? "#10b981"
      : item?.status === false
        ? item.is_new_missing
          ? "#f59e0b"
          : "#ef4444"
        : "#94a3b8",
  );

  const statusText = $derived(
    item?.status === true
      ? "已在曲库中"
      : item?.status === false
        ? item.is_new_missing
          ? "已加入待补清单"
          : "不在曲库中"
        : "无法查询曲库",
  );

  const icon = $derived(
    item?.status === true
      ? "✓"
      : item?.status === false
        ? item.is_new_missing
          ? "＋"
          : "✕"
        : "?",
  );

  function display(next: NotificationItem) {
    item = next;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void close(), 6000);
  }

  async function close() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    const id = item?.id;
    item = null;
    try {
      await dismissNotification(id);
    } catch {
      /* 窗口可能已关闭 */
    }
  }

  async function handleClick() {
    if (item?.copy_text) {
      try {
        await writeText(item.copy_text);
      } catch {
        /* 剪贴板失败时仍然关闭 */
      }
    }
    await close();
  }

  function loadPending(attempt = 0) {
    void getCurrentNotification()
      .then((pending) => {
        if (pending) display(pending);
      })
      .catch(() => {
        if (attempt < 2) {
          setTimeout(() => loadPending(attempt + 1), 400);
        }
      });
  }

  onMount(() => {
    listen<NotificationItem>("notification", (event) => {
      display(event.payload);
    }).then((dispose) => {
      unlisten = dispose;
      loadPending();
    });
    return () => {
      if (timer) clearTimeout(timer);
      unlisten?.();
    };
  });
</script>

<div class="notification-shell">
  {#if item}
    <div
      class="notification-card"
      role="button"
      tabindex="0"
      onclick={handleClick}
      onkeydown={(event) => {
        if (event.key === "Enter" || event.key === " ") void handleClick();
      }}
    >
      <div class="notification-accent" style:background={accent}></div>
      <div class="notification-body">
        <div class="notification-top">
          <span
            class="grid h-[26px] w-[26px] place-items-center rounded-lg text-[13px] font-black text-white"
            style:background={accent}
          >
            {icon}
          </span>
          <span class="notification-status" style:color={accent}>{statusText}</span>
          {#if item.player}
            <span class="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-slate-300">
              {item.player_name}
            </span>
          {/if}
        </div>
        <div class="notification-title">{item.title}</div>
        <div class="notification-artist">{item.artist || "未知歌手"}</div>
        <div class="notification-progress">
          <div style:background={accent}></div>
        </div>
        <div class="notification-hint">
          {item.copy_text ? "单击复制歌曲信息 · 6 秒后自动关闭" : "单击关闭 · 6 秒后自动关闭"}
        </div>
      </div>
    </div>
  {/if}
</div>
