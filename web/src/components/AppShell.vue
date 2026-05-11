<script setup lang="ts">
import { computed } from "vue";
import { zhCN as copy } from "../locales/zhCN";
import type { HealthPayload, NetworkEgressMode, NetworkModeOptionPayload } from "../types/api";

const props = defineProps<{
  health: HealthPayload | null;
}>();

const healthProblems = computed(() => props.health?.problems || []);
const proxyHealth = computed(() => props.health?.proxy);
const network = computed(() => props.health?.network);
const networkMode = computed<NetworkEgressMode>(() => network.value?.mode || "local");
const proxyEnabled = computed(() => networkMode.value === "dynamic_proxy" && Boolean(proxyHealth.value?.enabled));
const proxyAvailable = computed(() => Boolean(proxyHealth.value?.available));
const networkOptions = computed(() => {
  const modes = (network.value?.modes || {}) as Partial<Record<NetworkEgressMode, NetworkModeOptionPayload>>;
  return [
    {
      label: copy.app.networkModes.local,
      value: "local",
      disabled: false,
    },
    {
      label: copy.app.networkModes.dynamicProxy,
      value: "dynamic_proxy",
      disabled: !modes.dynamic_proxy?.available,
    },
    {
      label: copy.app.networkModes.zenproxy,
      value: "zenproxy",
      disabled: !modes.zenproxy?.available,
    },
  ];
});

function updateNetworkMode(mode: NetworkEgressMode, disabled?: boolean) {
  if (disabled || mode === networkMode.value) {
    return;
  }
  emit("update-network-mode", mode);
}

const emit = defineEmits<{
  logs: [];
  refresh: [];
  import: [];
  "update-network-mode": [mode: NetworkEgressMode];
}>();
</script>

<template>
  <main class="desk-shell">
    <header class="command-bar" :aria-label="copy.app.commandCenterLabel">
      <div class="command-title">
        <strong>{{ copy.app.title }}</strong>
        <span>{{ copy.app.eyebrow }}</span>
      </div>
      <div class="command-actions" :aria-label="copy.app.primaryActionsLabel">
        <n-tag round type="info">{{ health?.transport || copy.app.transportPending }}</n-tag>
        <n-tooltip trigger="hover">
          <template #trigger>
            <div class="network-mode-switch">
              <span>{{ copy.app.networkMode }}</span>
              <n-button-group size="small">
                <n-button
                  v-for="option in networkOptions"
                  :key="option.value"
                  :type="networkMode === option.value ? 'primary' : 'default'"
                  :secondary="networkMode !== option.value"
                  :disabled="option.disabled"
                  @click="updateNetworkMode(option.value as NetworkEgressMode, option.disabled)"
                >
                  {{ option.label }}
                </n-button>
              </n-button-group>
            </div>
          </template>
          <div class="preflight-tooltip">
            <div>{{ network?.message || copy.app.transportPending }}</div>
          </div>
        </n-tooltip>
        <n-tooltip v-if="proxyEnabled" trigger="hover">
          <template #trigger>
            <n-tag round :type="proxyAvailable ? 'success' : 'warning'">
              {{ proxyAvailable ? copy.app.proxyReady : copy.app.proxyUnavailable }}
            </n-tag>
          </template>
          <div class="preflight-tooltip">
            <div>{{ proxyHealth?.message || proxyHealth?.url }}</div>
          </div>
        </n-tooltip>
        <n-tooltip v-if="healthProblems.length" trigger="hover">
          <template #trigger>
            <n-tag round type="error">{{ copy.app.preflightFailed(healthProblems.length) }}</n-tag>
          </template>
          <div class="preflight-tooltip">
            <div v-for="problem in healthProblems" :key="problem">{{ problem }}</div>
          </div>
        </n-tooltip>
        <n-button secondary @click="emit('logs')">{{ copy.app.viewLogs }}</n-button>
        <n-button secondary @click="emit('refresh')">{{ copy.app.refresh }}</n-button>
        <n-button type="primary" @click="emit('import')">{{ copy.app.importAccount }}</n-button>
      </div>
    </header>

    <slot />
  </main>
</template>
