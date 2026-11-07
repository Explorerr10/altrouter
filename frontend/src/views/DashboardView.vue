<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { createStatsSocket } from '../api/ws'
import { useStatsStore } from '../stores/stats'
import StatCard from '../components/StatCard.vue'
import UplotChart from '../components/UplotChart.vue'
import { formatBytes, formatRate, formatUptime } from '../utils/format'
import { t } from '../i18n'

const stats = useStatsStore()

const info = ref(null)
const interfaces = ref([])
const clients = ref([])
let socket = null
let refreshTimer = null

const cpuData = computed(() => [stats.ts, stats.cpu])
const ramData = computed(() => [stats.ts, stats.ram])

const activeClients = computed(() => (clients.value || []).filter((c) => c.active).length)

const physicalIfaces = computed(() => (interfaces.value || []).filter((i) => i.physical))
const softIfaces = computed(() => (interfaces.value || []).filter((i) => !i.physical))

const ifaceGroups = computed(() => [
  { title: t('dash.physical'), list: physicalIfaces.value },
  { title: t('dash.soft'), list: softIfaces.value },
])

const internetText = computed(() => {
  if (!info.value) {
    return '—'
  }
  const net = info.value.internet
  if (net.dns_ok) {
    return t('dash.internetOk')
  }
  if (net.default_route) {
    return t('dash.internetLimited')
  }
  return t('dash.internetNo')
})

const ramNote = computed(() => {
  if (!stats.last) {
    return ''
  }
  return t('dash.of', {
    a: formatBytes(stats.last.ram_used_bytes),
    b: formatBytes(stats.last.ram_total_bytes),
  })
})

function ifaceRate(name, dir) {
  const rates = stats.ifaceRates[name]
  if (!rates) {
    return '—'
  }
  return formatRate(rates[dir])
}

async function refresh() {
  try {
    const [sys, ifaces, cl] = await Promise.all([
      api.get('/system/info'),
      api.get('/interfaces'),
      api.get('/clients'),
    ])
    info.value = sys
    interfaces.value = ifaces
    clients.value = cl
  } catch {
    return
  }
}

onMounted(() => {
  refresh()
  socket = createStatsSocket(
    (sample) => stats.push(sample),
    (connected) => stats.setConnected(connected),
  )
  refreshTimer = setInterval(refresh, 15000)
})

onBeforeUnmount(() => {
  if (socket) {
    socket.stop()
  }
  clearInterval(refreshTimer)
})
</script>

<template>
  <div class="dashboard">
    <span
      v-if="!stats.connected"
      class="offline-badge"
    >{{ t('dash.offline') }}</span>

    <div class="cards-grid">
      <StatCard
        :title="t('dash.device')"
        :value="info?.hostname ?? '—'"
        :note="info?.model || info?.board || ''"
      />
      <StatCard
        :title="t('dash.uptime')"
        :value="info ? formatUptime(info.uptime_seconds) : '—'"
        :note="info?.os || ''"
      />
      <StatCard
        :title="t('dash.internet')"
        :value="internetText"
        :note="info ? t('dash.defaultRoute', { v: info.internet.default_route ? t('common.yes') : t('common.no') }) : ''"
      />
      <StatCard
        :title="t('dash.activeClients')"
        :value="String(activeClients)"
        :note="t('dash.arpTotal', { n: clients.length })"
      />
    </div>

    <div class="charts-grid">
      <div class="card chart-card">
        <h3>{{ t('dash.cpu') }}</h3>
        <UplotChart
          :data="cpuData"
          label="CPU"
          color="#2563eb"
          :fill-color="'rgba(37,99,235,0.1)'"
        />
        <div class="chart-note">
          {{ info?.cpu_model || '' }}{{ info ? ` · ${t('dash.cores', { c: info.cpu_cores, t: info.cpu_threads })}` : '' }}
        </div>
      </div>
      <div class="card chart-card">
        <h3>{{ t('dash.mem') }}</h3>
        <UplotChart
          :data="ramData"
          label="RAM"
          color="#16a34a"
          :fill-color="'rgba(22,163,74,0.1)'"
        />
        <div class="chart-note">
          {{ ramNote }}{{ stats.last ? ` · ${t('dash.load', { p: stats.last.ram_percent.toFixed(1) })}` : '' }}
        </div>
      </div>
    </div>

    <div class="card table-card">
      <h3>{{ t('dash.ifaces') }}</h3>
      <table class="data fixed">
        <colgroup>
          <col class="c-name">
          <col class="c-state">
          <col class="c-speed">
          <col class="c-mtu">
          <col class="c-mac">
          <col class="c-ipv4">
          <col class="c-rate">
          <col class="c-rate">
          <col class="c-total">
          <col class="c-total">
        </colgroup>
        <thead>
          <tr>
            <th>{{ t('col.iface') }}</th>
            <th>{{ t('col.state') }}</th>
            <th>{{ t('col.speed') }}</th>
            <th>MTU</th>
            <th>MAC</th>
            <th>IPv4</th>
            <th>{{ t('col.rx') }}</th>
            <th>{{ t('col.tx') }}</th>
            <th>{{ t('col.rxTotal') }}</th>
            <th>{{ t('col.txTotal') }}</th>
          </tr>
        </thead>
        <tbody
          v-for="group in ifaceGroups"
          :key="group.title"
        >
          <tr>
            <td
              colspan="10"
              class="group-title"
            >
              {{ group.title }}
            </td>
          </tr>
          <tr v-if="!group.list.length">
            <td colspan="10">
              {{ t('dash.noIfaces') }}
            </td>
          </tr>
          <tr
            v-for="iface in group.list"
            :key="iface.name"
          >
            <td>
              <span class="mono">{{ iface.name }}</span>
              <span
                v-if="iface.management"
                class="badge"
              >{{ t('common.mgmt') }}</span>
            </td>
            <td>
              <span
                class="status-dot"
                :class="iface.up ? 'up' : 'down'"
              />
              {{ iface.up ? t('common.up') : t('common.down') }}
            </td>
            <td>{{ iface.speed_mbps ? t('common.mbps', { n: iface.speed_mbps }) : '—' }}</td>
            <td>{{ iface.mtu ?? '—' }}</td>
            <td class="mono">
              {{ iface.mac ?? '—' }}
            </td>
            <td>
              <span
                v-if="iface.ipv4.length"
                class="mono"
              >{{ iface.ipv4.join(', ') }}</span>
              <span v-else>—</span>
            </td>
            <td class="mono">
              {{ ifaceRate(iface.name, 'rx_bps') }}
            </td>
            <td class="mono">
              {{ ifaceRate(iface.name, 'tx_bps') }}
            </td>
            <td class="mono">
              {{ formatBytes(iface.rx_bytes) }}
            </td>
            <td class="mono">
              {{ formatBytes(iface.tx_bytes) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card table-card">
      <h3>{{ t('dash.clients') }}</h3>
      <table class="data">
        <thead>
          <tr>
            <th>{{ t('col.name') }}</th>
            <th>{{ t('col.ip') }}</th>
            <th>{{ t('col.mac') }}</th>
            <th>{{ t('col.iface') }}</th>
            <th>{{ t('col.status') }}</th>
            <th>{{ t('col.rx') }}</th>
            <th>{{ t('col.tx') }}</th>
            <th>{{ t('col.rxTotal') }}</th>
            <th>{{ t('col.txTotal') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="client in clients"
            :key="client.ip + client.mac"
          >
            <td>{{ client.hostname || '—' }}</td>
            <td class="mono">
              {{ client.ip }}
            </td>
            <td class="mono">
              {{ client.mac }}
            </td>
            <td class="mono">
              {{ client.interface }}
            </td>
            <td>
              <span
                class="status-dot"
                :class="client.active ? 'up' : 'down'"
              />
              {{ client.active ? t('common.active') : t('common.inactive') }}
            </td>
            <td class="mono">
              {{ formatRate(client.rx_bps) }}
            </td>
            <td class="mono">
              {{ formatRate(client.tx_bps) }}
            </td>
            <td class="mono">
              {{ formatBytes(client.rx_total) }}
            </td>
            <td class="mono">
              {{ formatBytes(client.tx_total) }}
            </td>
          </tr>
          <tr v-if="!clients.length">
            <td colspan="9">
              {{ t('dash.noClients') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.group-title {
  font-weight: 600;
  text-align: left;
  background: rgba(148, 163, 184, 0.08);
}
</style>
