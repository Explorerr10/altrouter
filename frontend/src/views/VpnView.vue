<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import PendingBanner from '../components/PendingBanner.vue'
import WireguardCard from '../components/WireguardCard.vue'
import { secondsLeft } from '../utils/ifaces'
import { t } from '../i18n'

const tunnels = ref([])
const pending = ref(null)
const error = ref('')
const countdown = ref(0)
let tickTimer = null

function updateCountdown() {
  countdown.value = pending.value ? secondsLeft(pending.value.deadline) : 0
  if (pending.value && countdown.value <= 0) {
    refresh()
  }
}

async function refresh() {
  try {
    const cfg = await api.get('/network/interfaces/config')
    tunnels.value = cfg.wireguard ?? []
    pending.value = cfg.pending
    updateCountdown()
  } catch (err) {
    error.value = err.message || t('common.loadError')
  }
}

function onSectionApplied(newPending) {
  pending.value = newPending
  refresh()
}

async function confirmPending() {
  error.value = ''
  try {
    await api.post('/network/interfaces/confirm', {})
  } catch (err) {
    error.value = err.message
  }
  await refresh()
}

async function rollbackPending() {
  error.value = ''
  try {
    await api.post('/network/interfaces/rollback', {})
  } catch (err) {
    error.value = err.message
  }
  await refresh()
}

const busy = computed(() => pending.value !== null)

onMounted(() => {
  refresh()
  tickTimer = setInterval(updateCountdown, 1000)
})

onBeforeUnmount(() => {
  clearInterval(tickTimer)
})
</script>

<template>
  <div class="rules-page">
    <p
      v-if="error"
      class="form-error"
    >
      {{ error }}
    </p>

    <PendingBanner
      v-if="pending"
      :pending="pending"
      :countdown="countdown"
      @confirm="confirmPending"
      @rollback="rollbackPending"
    />

    <WireguardCard
      :tunnels="tunnels"
      :busy="busy"
      @applied="onSectionApplied"
    />
  </div>
</template>
