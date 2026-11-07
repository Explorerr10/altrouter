<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import PeerConfigDialog from './PeerConfigDialog.vue'
import WireguardDialog from './WireguardDialog.vue'
import { bytesText, handshakeText, ifaceFromForm, tunnelStatus } from '../utils/wireguard'
import { t } from '../i18n'

const props = defineProps({
  tunnels: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['applied'])

const error = ref('')
const saving = ref(false)
const status = ref({})
const dialog = ref(null)
const dialogError = ref('')
const exportTunnel = ref(null)
let statusTimer = null

async function refreshStatus() {
  try {
    const resp = await api.get('/network/vpn/status')
    status.value = resp.items ?? {}
  } catch {
    status.value = {}
  }
}

async function saveList(items) {
  error.value = ''
  saving.value = true
  try {
    const resp = await api.put('/network/vpn/wireguard', { items })
    emit('applied', resp.pending)
    return true
  } catch (err) {
    error.value = err.message || t('common.applyError')
    return false
  } finally {
    saving.value = false
  }
}

async function saveTunnel(wg) {
  dialogError.value = ''
  const next = props.tunnels.map(ifaceFromForm)
  const index = next.findIndex((item) => item.id === wg.id)
  if (index >= 0) {
    next[index] = wg
  } else {
    next.push(wg)
  }
  if (await saveList(next)) {
    dialog.value = null
  }
}

async function removeTunnel(tunnel) {
  if (!confirm(t('wg.delAsk', { n: tunnel.name }))) return
  if (await saveList(props.tunnels.filter((item) => item.id !== tunnel.id).map(ifaceFromForm))) {
    dialog.value = null
  }
}

onMounted(() => {
  refreshStatus()
  statusTimer = setInterval(refreshStatus, 10000)
})

onBeforeUnmount(() => {
  clearInterval(statusTimer)
})
</script>

<template>
  <div class="card table-card">
    <div class="card-head">
      <h3>WireGuard</h3>
      <div class="dialog-actions">
        <button
          class="btn small"
          :disabled="props.busy"
          @click="dialogError = ''; dialog = { initial: null }"
        >
          {{ t('wg.add') }}
        </button>
      </div>
    </div>
    <p
      v-if="error"
      class="form-error table-error"
    >
      {{ error }}
    </p>
    <table class="data">
      <thead>
        <tr>
          <th>{{ t('wg.tunnel') }}</th>
          <th>{{ t('wg.addr') }}</th>
          <th>{{ t('wg.port') }}</th>
          <th>{{ t('wg.routing') }}</th>
          <th>{{ t('wg.peersStatus') }}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="tunnel in props.tunnels"
          :key="tunnel.id"
        >
          <td>
            {{ tunnel.name }}
            <span
              v-if="!tunnel.enabled"
              class="muted"
            >{{ t('wg.off') }}</span>
          </td>
          <td>
            <span class="mono">{{ tunnel.address }}</span>
          </td>
          <td>
            <span class="mono">{{ tunnel.listen_port }}</span>
          </td>
          <td>{{ t('wg.route.' + tunnel.route_mode) }}</td>
          <td class="peers-cell">
            <div
              v-for="peer in tunnel.peers"
              :key="peer.name"
              class="peer-status"
            >
              <span
                class="status-dot"
                :class="{ up: tunnelStatus(status, tunnel).some((s) => s.public_key === peer.public_key && s.handshake) }"
              />
              <span>{{ peer.name }}</span>
              <span
                v-for="info in tunnelStatus(status, tunnel).filter((s) => s.public_key === peer.public_key)"
                :key="info.public_key"
                class="muted"
              >
                {{ handshakeText(info.handshake) }} · ↓{{ bytesText(info.rx) }} ↑{{ bytesText(info.tx) }}
              </span>
            </div>
            <span
              v-if="!tunnel.peers.length"
              class="muted"
            >{{ t('wg.noPeers') }}</span>
          </td>
          <td>
            <button
              class="btn small"
              :disabled="!tunnel.peers.length"
              @click="exportTunnel = tunnel"
            >
              {{ t('wg.cfgBtn') }}
            </button>
            <button
              class="btn small"
              @click="dialogError = ''; dialog = { initial: tunnel }"
            >
              {{ t('common.edit') }}
            </button>
            <button
              class="btn small"
              :disabled="saving || props.busy"
              @click="removeTunnel(tunnel)"
            >
              {{ t('common.delete') }}
            </button>
          </td>
        </tr>
        <tr v-if="!props.tunnels.length">
          <td colspan="6">
            {{ t('wg.none') }}
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint-text table-hint">
      {{ t('wg.hint') }}
    </p>

    <WireguardDialog
      v-if="dialog"
      :initial="dialog.initial"
      :error="dialogError"
      :busy="saving || props.busy"
      @close="dialog = null"
      @save="saveTunnel"
    />

    <PeerConfigDialog
      v-if="exportTunnel"
      :tunnel="exportTunnel"
      @close="exportTunnel = null"
    />
  </div>
</template>
