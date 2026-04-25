<script setup lang="ts">
import { zhCN as copy } from "../locales/zhCN";

const props = defineProps<{
  accountId: string;
  enabled: boolean;
  time: string;
}>();

const emit = defineEmits<{
  update: [accountId: string, enabled: boolean, time: string];
}>();

function updateEnabled(enabled: boolean) {
  emit("update", props.accountId, enabled, props.time || "00:00:00");
}

function updateTime(event: Event) {
  const target = event.target as HTMLInputElement;
  emit("update", props.accountId, props.enabled, target.value);
}
</script>

<template>
  <div class="schedule-cell">
    <n-switch :value="enabled" :aria-label="copy.schedule.enableLabel" @update:value="updateEnabled" />
    <input
      class="time-input"
      type="time"
      step="1"
      :value="time || '00:00:00'"
      :aria-label="copy.schedule.timeLabel"
      @change="updateTime"
    />
  </div>
</template>