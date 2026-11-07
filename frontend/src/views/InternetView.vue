<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import InterfaceDialog from '../components/InterfaceDialog.vue'
import PendingBanner from '../components/PendingBanner.vue'
import StaticRoutesCard from '../components/StaticRoutesCard.vue'
import WanPolicyCard from '../components/WanPolicyCard.vue'
import { secondsLeft } from '../utils/ifaces'
import { t } from '../i18n'

const items = ref({})
const routes = ref([])
const wan = ref({ policies: {} })
const management = ref('')
const live = ref([])
const pending = ref(null)
const error = ref('')
const dialog = ref(null)
const dialogError = ref('')
const busy = ref(false)
const countdown = ref(0)
let tickTimer = null

const rows = computed(() =>
  live.value.map((iface) => ({ ...iface, cfg: items.value[iface.name] ?? null })),
)

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
    const [cfg, ifaces] = await Promise.all([
      api.get('/network/interfaces/config'),
      api.get('/interfaces'),
    ])
    items.value = cfg.items ?? {}
    routes.value = cfg.routes ?? []
    wan.value = cfg.wan ?? { policies: {} }
    management.value = cfg.management
    pending.value = cfg.pending
    live.value = ifaces
    updateCountdown()
  } catch (err) {
    error.value = err.message || t('common.loadError')
  }
}

async function toggleLink(row) {
  if (row.up && !window.confirm(t('net.linkDownAsk', { n: row.name }))) return
  busy.value = true
  try {
    await api.put(`/network/interfaces/${row.name}/link`, { up: !row.up })
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
  await refresh()
}

function openDialog(row) {
  dialogError.value = ''
  dialog.value = { name: row.name, initial: row.cfg }
}

async function saveDialog(item) {
  dialogError.value = ''
  busy.value = true
  try {
    const body = { items: { ...items.value, [item.name]: item } }
    const resp = await api.put('/network/interfaces/config', body)
    pending.value = resp.pending
    dialog.value = null
    await refresh()
  } catch (err) {
    dialogError.value = err.message || t('common.applyError')
  } finally {
    busy.value = false
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

function onSectionApplied(newPending) {
  pending.value = newPending
  refresh()
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
  <div class="internet-page">
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
      <h3>{{ t('net.connections') }}</h3>
      <table class="data">
        <thead>
          <tr>
            <th>{{ t('col.iface') }}</th>
            <th>{{ t('col.role') }}</th>
            <th>IPv4</th>
            <th>MTU</th>
            <th>{{ t('col.state') }}</th>
            <th>Link</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.name"
          >
            <td>
              <span class="mono">{{ row.name }}</span>
              <span
                v-if="row.management"
                class="badge"
              >{{ t('common.mgmt') }}</span>
            </td>
            <td>
              <span
                v-if="row.cfg"
                class="role-badge"
                :class="row.cfg.role"
              >{{ t('role.' + row.cfg.role) }}</span>
              <span v-else>—</span>
            </td>
            <td>
              <span
                v-if="row.cfg && row.cfg.ipv4 === 'dhcp'"
                class="muted"
              >DHCP</span>
              <span
                v-else-if="row.cfg && row.cfg.address"
                class="mono"
              >{{ row.cfg.address }}</span>
              <span
                v-else-if="row.ipv4.length"
                class="mono muted"
              >{{ row.ipv4.join(', ') }} {{ t('net.fact') }}</span>
              <span v-else>—</span>
            </td>
            <td>{{ row.cfg?.mtu ?? row.mtu ?? '—' }}</td>
            <td>
              <span
                class="status-dot"
                :class="row.up ? 'up' : 'down'"
              />
              {{ row.up ? (row.speed_mbps ? t('common.mbps', { n: row.speed_mbps }) : t('common.up')) : t('common.down') }}
            </td>
            <td>
              <label
                class="switch"
                :title="row.management ? t('net.mgmtLocked') : ''"
              >
                <input
                  type="checkbox"
                  :checked="row.up"
                  :disabled="busy || row.management"
                  @change="toggleLink(row)"
                >
                <span class="slider" />
              </label>
            </td>
            <td>
              <button
                class="btn small"
                :disabled="row.management"
                :title="row.management ? t('net.mgmtLocked') : ''"
                @click="openDialog(row)"
              >
                {{ t('common.edit') }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="7">
              {{ t('net.noIfaces') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="hint-text">
      {{ t('net.hint1') }}
      <template v-if="management">
        {{ t('net.hint2', { n: management }) }}
      </template>
      {{ t('net.hint3') }}
    </p>

    <WanPolicyCard
      :wan-ifaces="wanIfaces"
      :policies="wan.policies"
      :mode="wan.mode || 'failover'"
      :busy="busy"
      @applied="onSectionApplied"
    />

    <StaticRoutesCard
      :routes="routes"
      :busy="busy"
      @applied="onSectionApplied"
    />

    <InterfaceDialog
      v-if="dialog"
      :name="dialog.name"
      :initial="dialog.initial"
      :error="dialogError"
      :busy="busy"
      @close="dialog = null"
      @save="saveDialog"
    />
  </div>
</template>
