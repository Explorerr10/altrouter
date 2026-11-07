<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import PendingBanner from '../components/PendingBanner.vue'
import SegmentClientsDialog from '../components/SegmentClientsDialog.vue'
import SegmentDialog from '../components/SegmentDialog.vue'
import { secondsLeft } from '../utils/ifaces'
import { t } from '../i18n'

const items = ref({})
const segments = ref([])
const live = ref([])
const pending = ref(null)
const error = ref('')
const dialog = ref(null)
const clientsDialog = ref(null)
const dialogError = ref('')
const busy = ref(false)
const countdown = ref(0)
let tickTimer = null

const segByPort = computed(() => {
  const map = {}
  for (const seg of segments.value) {
    for (const port of seg.interfaces) {
      map[port] = seg
    }
  }
  return map
})

const lanIfaces = computed(() =>
  Object.values(items.value).filter((cfg) => cfg.role === 'lan'),
)
const freeLan = computed(() => lanIfaces.value.filter((cfg) => !segByPort.value[cfg.name]))

function updateCountdown() {
  countdown.value = pending.value ? secondsLeft(pending.value.deadline) : 0
  if (pending.value && countdown.value <= 0) {
    refresh()
  }
}

async function refresh() {
  try {
    const [cfg, ifaces] = await Promise.all([
      api.get('/network/interfaces/config'),
      api.get('/interfaces'),
    ])
    items.value = cfg.items ?? {}
    segments.value = cfg.segments ?? []
    pending.value = cfg.pending
    live.value = ifaces
    updateCountdown()
  } catch (err) {
    error.value = err.message || t('common.loadError')
  }
}

function openCreate() {
  dialogError.value = ''
  dialog.value = { initial: null }
}

function openEdit(seg) {
  dialogError.value = ''
  dialog.value = { initial: seg }
}

function openClients(seg) {
  dialogError.value = ''
  clientsDialog.value = seg
}

function portsForDialog() {
  const editingPorts = dialog.value?.initial?.interfaces ?? []
  return [...freeLan.value.map((cfg) => cfg.name), ...editingPorts]
}

async function saveSegment(seg) {
  dialogError.value = ''
  busy.value = true
  try {
    const others = segments.value.filter((s) => s.id !== seg.id)
    const resp = await api.put('/network/segments', { segments: [...others, seg] })
    pending.value = resp.pending
    dialog.value = null
    clientsDialog.value = null
    await refresh()
  } catch (err) {
    dialogError.value = err.message || t('common.applyError')
  } finally {
    busy.value = false
  }
}

async function removeSegment(seg) {
  if (!window.confirm(t('home.deleteAsk', { n: seg.name }))) {
    return
  }
  error.value = ''
  try {
    const resp = await api.put('/network/segments', {
      segments: segments.value.filter((s) => s.id !== seg.id),
    })
    pending.value = resp.pending
    await refresh()
  } catch (err) {
    error.value = err.message
  }
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

function isUp(name) {
  return Boolean(live.value.find((iface) => iface.name === name)?.up)
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
  <div class="home-net-page">
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

    <div class="card table-card">
      <div class="card-head">
        <h3>{{ t('home.segments') }}</h3>
        <button
          class="btn small"
          :disabled="!freeLan.length"
          :title="!freeLan.length ? t('home.noFreePorts') : ''"
          @click="openCreate"
        >
          {{ t('home.add') }}
        </button>
      </div>
      <table class="data">
        <thead>
          <tr>
            <th>{{ t('home.seg') }}</th>
            <th>{{ t('home.bridge') }}</th>
            <th>{{ t('home.ports') }}</th>
            <th>{{ t('home.subnet') }}</th>
            <th>DHCP</th>
            <th>{{ t('home.reservations') }}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="seg in segments"
            :key="seg.id"
          >
            <td>{{ seg.name }}</td>
            <td><span class="mono">arbr-{{ seg.id }}</span></td>
            <td>
              <span
                v-for="(port, index) in seg.interfaces"
                :key="port"
              >
                <span
                  class="status-dot"
                  :class="isUp(port) ? 'up' : 'down'"
                />{{ port }}<span v-if="index < seg.interfaces.length - 1">, </span>
              </span>
            </td>
            <td><span class="mono">{{ seg.address }}</span></td>
            <td>
              <template v-if="seg.dhcp?.enabled">
                {{ seg.dhcp.pool_start }}–{{ seg.dhcp.pool_end }}
              </template>
              <span
                v-else
                class="muted"
              >{{ t('common.off') }}</span>
            </td>
            <td>{{ seg.reservations?.length ?? 0 }}</td>
            <td>
              <button
                class="btn small"
                @click="openEdit(seg)"
              >
                {{ t('common.edit') }}
              </button>
              <button
                class="btn small"
                @click="openClients(seg)"
              >
                {{ t('home.clients') }}
              </button>
              <button
                class="btn small"
                @click="removeSegment(seg)"
              >
                {{ t('common.delete') }}
              </button>
            </td>
          </tr>
          <tr v-if="!segments.length">
            <td colspan="7">
              {{ t('home.none') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3>{{ t('home.freePortsTitle') }}</h3>
      <p
        v-if="freeLan.length"
        class="hint-text"
      >
        <span
          v-for="cfg in freeLan"
          :key="cfg.name"
          class="mono"
        >{{ cfg.name }} ({{ cfg.address }}) </span> {{ t('home.freePortsHint') }}
      </p>
      <p
        v-else
        class="hint-text"
      >
        {{ t('home.allPortsUsed') }}
      </p>
    </div>

    <p class="hint-text">
      {{ t('home.hint') }}
    </p>

    <SegmentDialog
      v-if="dialog"
      :initial="dialog.initial"
      :free-ports="portsForDialog()"
      :error="dialogError"
      :busy="busy"
      @close="dialog = null"
      @save="saveSegment"
    />

    <SegmentClientsDialog
      v-if="clientsDialog"
      :segment="clientsDialog"
      :error="dialogError"
      :busy="busy"
      @close="clientsDialog = null"
      @save="saveSegment"
    />
  </div>
</template>
