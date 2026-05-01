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
    <div class="status-banner-content">
      <span>{{ banner.text }}</span>
      <span v-if="banner.links?.length" class="status-banner-links">
        <a
          v-for="link in banner.links"
          :key="`${link.text}:${link.href}`"
          class="status-banner-link"
          :href="link.href"
          target="_blank"
          rel="noopener noreferrer"
        >
          {{ link.text }}
        </a>
      </span>
      <a
        v-else-if="banner.linkHref"
        class="status-banner-link"
        :href="banner.linkHref"
        target="_blank"
        rel="noopener noreferrer"
      >
        {{ banner.linkText || "打开" }}
      </a>
    </div>
  </n-alert>
</template>
