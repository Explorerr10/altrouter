<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import FirewallCard from '../components/FirewallCard.vue'
import LocalDnsCard from '../components/LocalDnsCard.vue'
import PendingBanner from '../components/PendingBanner.vue'
import PortForwardsCard from '../components/PortForwardsCard.vue'
import { secondsLeft } from '../utils/ifaces'
import { t } from '../i18n'

const items = ref({})
const segments = ref([])
const rules = ref([])
const forwards = ref([])
const dnsRecords = ref([])
const pending = ref(null)
const error = ref('')
const countdown = ref(0)
let tickTimer = null

const zones = computed(() => [
  { value: 'wan', label: t('rules.zoneWan') },
  { value: 'lan', label: t('rules.zoneLan') },
  ...segments.value.map((seg) => ({ value: seg.id, label: t('rules.zoneSeg', { n: seg.name }) })),
])

const wanIfaces = computed(() =>
  Object.values(items.value).filter((cfg) => cfg.role === 'wan').map((cfg) => cfg.name),
)

function updateCountdown() {
  countdown.value = pending.value ? secondsLeft(pending.value.deadline) : 0
  if (pending.value && countdown.value <= 0) {
    refresh()
  }
}

async function refresh() {
  try {
    const cfg = await api.get('/network/interfaces/config')
    items.value = cfg.items ?? {}
    segments.value = cfg.segments ?? []
    rules.value = cfg.rules ?? []
    forwards.value = cfg.forwards ?? []
    dnsRecords.value = cfg.dns ?? []
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

    <FirewallCard
      :rules="rules"
      :zones="zones"
      :busy="pending !== null"
      @applied="onSectionApplied"
    />

    <PortForwardsCard
      :forwards="forwards"
      :wan-ifaces="wanIfaces"
      :busy="pending !== null"
      @applied="onSectionApplied"
    />

    <LocalDnsCard
      :records="dnsRecords"
      :busy="pending !== null"
      @applied="onSectionApplied"
    />
  </div>
</template>
