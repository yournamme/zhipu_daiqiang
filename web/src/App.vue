<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { dateZhCN, zhCN as naiveZhCN } from "naive-ui";
import AccountContextModal from "./components/AccountContextModal.vue";
import AccountTable from "./components/AccountTable.vue";
import AppShell from "./components/AppShell.vue";
import DashboardStats from "./components/DashboardStats.vue";
import ImportAccountModal from "./components/ImportAccountModal.vue";
import StatusBanner from "./components/StatusBanner.vue";
import { useDashboard } from "./composables/useDashboard";
import type { AccountDetailResponse, AccountImportPayload } from "./types/api";

const dashboard = useDashboard();
const showImport = ref(false);
const showContext = ref(false);
const selectedDetail = ref<AccountDetailResponse | null>(null);

const importing = computed(() => dashboard.actionKey.value === "import");

const themeOverrides = {
  common: {
    primaryColor: "#c99724",
    primaryColorHover: "#b8891e",
    primaryColorPressed: "#8f6a16",
    borderRadius: "14px",
    fontFamily: "Fira Sans, Segoe UI, sans-serif",
    fontFamilyMono: "Fira Code, ui-monospace, SFMono-Regular, Menlo, monospace"
  },
  Button: {
    heightLarge: "46px",
    borderRadiusMedium: "12px"
  },
  Card: {
    borderRadius: "20px"
  }
};

onMounted(async () => {
  await dashboard.refreshDashboard();
  dashboard.startPolling();
});

function openContext(detail: AccountDetailResponse) {
  selectedDetail.value = detail;
  showContext.value = true;
}

async function submitImport(payload: AccountImportPayload) {
  await dashboard.importAccount(payload);
  showImport.value = false;
}

async function updateProduct(accountId: string, productId: string) {
  if (!productId) {
    return;
  }
  await dashboard.updatePreferences(accountId, { selected_product_id: productId });
}

async function updateSchedule(accountId: string, enabled: boolean, time: string) {
  await dashboard.updatePreferences(accountId, {
    schedule_enabled: enabled,
    scheduled_start_time: time
  });
}
</script>

<template>
  <n-config-provider :locale="naiveZhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <AppShell :health="dashboard.health.value" @refresh="dashboard.refreshDashboard()" @import="showImport = true">
      <StatusBanner :banner="dashboard.banner.value" @close="dashboard.clearBanner" />
      <DashboardStats
        :accounts-total="dashboard.accountsTotal.value"
        :running-total="dashboard.runningTotal.value"
        :qr-total="dashboard.qrTotal.value"
      />
      <AccountTable
        :details="dashboard.details.value"
        :loading="dashboard.loading.value"
        :action-key="dashboard.actionKey.value"
        @open-context="openContext"
        @select-product="updateProduct"
        @update-schedule="updateSchedule"
        @sync="dashboard.syncAccount"
        @delete="dashboard.deleteAccount"
        @run="dashboard.runAccount"
        @pause="dashboard.pauseAccount"
      />
    </AppShell>

    <ImportAccountModal v-model:show="showImport" :loading="importing" @submit="submitImport" />
    <AccountContextModal v-model:show="showContext" :detail="selectedDetail" />
  </n-config-provider>
</template>