<script lang="ts">
  import { untrack } from "svelte";
  import { X, Server, Bell, ShieldCheck, Loader2, Settings as SettingsIcon } from "lucide-svelte";
  import { saveSettings, testConnection } from "./api";
  import type { ActionResponse, Snapshot } from "./types";

  let {
    snapshot,
    onclose,
    onsaved,
    onmessage,
  }: {
    snapshot: Snapshot;
    onclose: () => void;
    onsaved: (response: ActionResponse) => void;
    onmessage: (message: string, kind?: "info" | "success" | "error") => void;
  } = $props();

  let serverUrl = $state(untrack(() => snapshot.subsonic.server_url));
  let username = $state(untrack(() => snapshot.subsonic.username));
  let password = $state("");
  let verifySsl = $state(untrack(() => snapshot.subsonic.verify_ssl));
  let clearPassword = $state(false);
  let reminderMode = $state(untrack(() => snapshot.settings.reminder_mode));
  let cooldown = $state(untrack(() => snapshot.settings.reminder_cooldown_minutes));
  let saving = $state(false);
  let testing = $state(false);
  let testResult = $state<{ ok: boolean; message: string } | null>(null);

  async function test() {
    testing = true;
    testResult = null;
    try {
      const result = await testConnection({
        server_url: serverUrl,
        username,
        password,
        verify_ssl: verifySsl,
      });
      testResult = { ok: result.ok, message: result.message };
    } catch (error) {
      testResult = { ok: false, message: String(error) };
    } finally {
      testing = false;
    }
  }

  async function save() {
    const minutes = Number(cooldown);
    if (!Number.isInteger(minutes) || minutes < 0 || minutes > 1440) {
      onmessage("提醒冷却时间需在 0~1440 分钟之间", "error");
      return;
    }
    saving = true;
    try {
      const response = await saveSettings({
        server_url: serverUrl,
        username,
        password,
        verify_ssl: verifySsl,
        reminder_mode: reminderMode,
        reminder_cooldown_minutes: minutes,
        last_tab: snapshot.settings.last_tab,
        clear_password: clearPassword,
      });
      onsaved(response);
      onmessage(response.message, "success");
      onclose();
    } catch (error) {
      onmessage(String(error), "error");
    } finally {
      saving = false;
    }
  }
</script>

<div
  class="modal-backdrop"
  role="presentation"
  onclick={(event) => {
    if (event.target === event.currentTarget) onclose();
  }}
>
  <div class="modal" role="dialog" aria-modal="true" aria-label="设置">
    <div class="modal-header">
      <div class="grid h-10 w-10 place-items-center rounded-xl bg-indigo-50 text-indigo-600">
        <SettingsIcon />
      </div>
      <div class="min-w-0">
        <div class="modal-title">设置</div>
        <div class="modal-sub">Subsonic 服务器与提醒策略</div>
      </div>
      <button class="btn btn-ghost ml-auto" onclick={onclose} aria-label="关闭">
        <X size={16} />
      </button>
    </div>

    <div class="modal-body">
      <div class="section-title"><Server size={14} /> Subsonic 服务器 <span class="section-line"></span></div>
      <div class="field">
        <label for="server-url">服务器地址</label>
        <input
          id="server-url"
          type="text"
          bind:value={serverUrl}
          placeholder="https://your-server.com:port/"
          autocomplete="off"
        />
        <span class="hint">可填写根地址，也可直接粘贴包含 /rest 的地址。</span>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="username">用户名</label>
          <input id="username" type="text" bind:value={username} autocomplete="username" />
        </div>
        <div class="field">
          <label for="password">密码</label>
          <input
            id="password"
            type="password"
            bind:value={password}
            placeholder={snapshot.subsonic.password_set ? "已保存，留空保持不变" : "请输入密码"}
            autocomplete="current-password"
          />
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-4">
        <label class="check">
          <input type="checkbox" bind:checked={verifySsl} />
          校验 SSL 证书
        </label>
        {#if snapshot.subsonic.password_set}
          <label class="check">
            <input type="checkbox" bind:checked={clearPassword} />
            清空已保存密码
          </label>
        {/if}
      </div>
      <div class="flex items-center gap-2">
        <button class="btn btn-soft" onclick={test} disabled={testing}>
          {#if testing}<Loader2 size={14} class="animate-spin" />{:else}<ShieldCheck size={14} />{/if}
          测试连接
        </button>
        {#if testResult}
          <span
            class="text-[12px] font-semibold"
            class:text-emerald-600={testResult.ok}
            class:text-red-600={!testResult.ok}
          >
            {testResult.message}
          </span>
        {/if}
      </div>

      <div class="section-title"><Bell size={14} /> 提醒策略 <span class="section-line"></span></div>
      <div class="field-row">
        <div class="field">
          <label for="reminder-mode">提醒模式</label>
          <select id="reminder-mode" bind:value={reminderMode}>
            <option value="new_missing">仅新缺失歌曲</option>
            <option value="missing">所有缺失歌曲</option>
            <option value="all">全部歌曲</option>
            <option value="off">关闭提醒</option>
          </select>
        </div>
        <div class="field">
          <label for="cooldown">冷却时间（分钟）</label>
          <input id="cooldown" type="number" min="0" max="1440" bind:value={cooldown} />
          <span class="hint">同一首歌在冷却时间内不重复弹窗。</span>
        </div>
      </div>
    </div>

    <div class="modal-footer">
      <button class="btn btn-ghost" onclick={onclose} disabled={saving}>取消</button>
      <button class="btn btn-primary" onclick={save} disabled={saving}>
        {#if saving}<Loader2 size={14} class="animate-spin" />{/if}
        保存设置
      </button>
    </div>
  </div>
</div>
