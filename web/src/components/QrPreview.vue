<script setup lang="ts">
import { zhCN as copy } from "../locales/zhCN";
import type { PaymentTaskRecord } from "../types/api";

const props = defineProps<{
  task: PaymentTaskRecord | null;
  productUnit?: string;
}>();

function paymentSummary() {
  const task = props.task;
  if (!task) {
    return "";
  }
  const productName = task.product_name || task.product_id;
  const cycle = props.productUnit ? `/${props.productUnit}` : "";
  const amount = task.amount ? ` ${task.amount}` : "";
  return `${productName}${cycle}${amount}`;
}
</script>

<template>
  <div class="qr-cell">
    <img v-if="task?.qr_base64" :src="task.qr_base64" :alt="copy.qr.alt" decoding="sync" />
    <div v-else class="qr-empty">{{ copy.qr.empty }}</div>
    <small v-if="task">{{ paymentSummary() }}</small>
  </div>
</template>
