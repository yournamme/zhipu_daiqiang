<script setup lang="ts">
import type { StatusBanner } from "../composables/useDashboard";

defineProps<{
  banner: StatusBanner | null;
}>();

const emit = defineEmits<{
  close: [];
}>();
</script>

<template>
  <n-alert
    v-if="banner"
    class="status-banner"
    :type="banner.tone"
    closable
    role="status"
    @close="emit('close')"
  >
    {{ banner.text }}
  </n-alert>
</template>