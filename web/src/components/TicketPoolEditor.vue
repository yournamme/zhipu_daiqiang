<script setup lang="ts">
import { zhCN as copy } from "../locales/zhCN";

const props = defineProps<{
    accountId: string;
    enabled: boolean;
    size: number;
    drainIntervalMs: number;
    collected: number;
    target: number;
}>();

const emit = defineEmits<{
    update: [accountId: string, enabled: boolean, size: number, drainIntervalMs: number];
    clearPool: [accountId: string];
}>();

const DEFAULT_POOL_SIZE = 5;

function toggleEnabled(enabled: boolean) {
    const nextSize = enabled
        ? Math.max(props.size || 0, DEFAULT_POOL_SIZE)
        : 0;
    emit("update", props.accountId, enabled, nextSize, props.drainIntervalMs);
}

function updateSize(event: Event) {
    const raw = parseInt((event.target as HTMLInputElement).value, 10);
    const size = Math.max(1, Math.min(50, isNaN(raw) ? DEFAULT_POOL_SIZE : raw));
    emit("update", props.accountId, true, size, props.drainIntervalMs);
}

function updateDrainInterval(event: Event) {
    const raw = parseInt((event.target as HTMLInputElement).value, 10);
    const intervalMs = Math.max(0, Math.min(10000, isNaN(raw) ? 0 : raw));
    emit("update", props.accountId, true, props.size || DEFAULT_POOL_SIZE, intervalMs);
}
</script>

<template>
    <div class="ticket-pool-cell">
        <n-switch
            :value="enabled"
            :aria-label="copy.ticketPool.enableLabel"
            @update:value="toggleEnabled"
        />
        <template v-if="enabled">
            <input
                class="pool-size-input"
                type="number"
                min="1"
                max="50"
                step="1"
                :value="size"
                :title="copy.ticketPool.sizeHint"
                :aria-label="copy.ticketPool.sizeLabel"
                :disabled="collected > 0"
                @change="updateSize"
            />
            <label class="pool-interval-control">
                <span>{{ copy.ticketPool.intervalLabel }}</span>
                <input
                    class="pool-interval-input"
                    type="number"
                    min="0"
                    max="10000"
                    step="50"
                    :value="drainIntervalMs"
                    :title="copy.ticketPool.intervalHint"
                    :aria-label="copy.ticketPool.intervalLabel"
                    @change="updateDrainInterval"
                />
            </label>
            <span
                v-if="target > 0"
                :class="collected >= target ? 'pool-ready' : 'pool-filling'"
            >
                {{ copy.ticketPool.status(collected, target) }}
            </span>
            <n-button
                v-if="collected > 0"
                size="tiny"
                type="warning"
                ghost
                @click="emit('clearPool', accountId)"
            >
                {{ copy.ticketPool.clearPool }}
            </n-button>
        </template>
        <span v-else class="schedule-time-readonly">{{
            copy.ticketPool.off
        }}</span>
    </div>
</template>
