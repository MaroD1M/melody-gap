<script lang="ts">
  import MainApp from "./lib/MainApp.svelte";
  import NotificationWindow from "./lib/NotificationWindow.svelte";

  const isNotification =
    new URLSearchParams(window.location.search).get("window") === "notification";

  if (isNotification) {
    document.documentElement.classList.add("notification-mode");
  }
</script>

{#if isNotification}
  <NotificationWindow />
{:else}
  <MainApp />
{/if}
