<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { policyFromForm, policyToForm } from '../utils/segments'
import { t } from '../i18n'

const props = defineProps({
  wanIfaces: { type: Array, default: () => [] },
  policies: { type: Object, default: () => ({}) },
  mode: { type: String, default: 'failover' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['applied'])

const form = reactive({})
const mode = ref(props.mode)
const status = ref({})
const error = ref('')
const saving = ref(false)
let statusTimer = null

function rebuild() {
  for (const iface of props.wanIfaces) {
    form[iface] = policyToForm(props.policies[iface])
  }
  for (const key of Object.keys(form)) {
    if (!props.wanIfaces.includes(key)) {
      delete form[key]
    }
  }
}

watch(
  () => [props.wanIfaces, props.policies],
  rebuild,
  { immediate: true, deep: true },
)

watch(() => props.mode, (value) => {
  mode.value = value
})

async function refreshStatus() {
  try {
    const resp = await api.get('/network/wan/status')
    status.value = resp.items ?? {}
  } catch {
    status.value = {}
  }
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    const policies = {}
    for (const iface of props.wanIfaces) {
      policies[iface] = policyFromForm(form[iface])
    }
    const resp = await api.put('/network/wan', { policies, mode: mode.value })
    emit('applied', resp.pending)
  } catch (err) {
    error.value = err.message || t('common.applyError')
  } finally {
    saving.value = false
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
      <h3>{{ t('wan.title') }}</h3>
      <button
        class="btn small"
        :disabled="saving || props.busy"
        @click="save"
      >
        {{ t('common.save') }}
      </button>
    </div>
    <div class="inline-fields mode-line">
      <span>{{ t('wan.mode') }}</span>
      <select v-model="mode">
        <option value="failover">
          {{ t('wan.failover') }}
        </option>
        <option
          value="balance"
          :disabled="props.wanIfaces.length < 2"
        >
          {{ t('wan.balance') }}
        </option>
      </select>
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
          <th>{{ t('wan.conn') }}</th>
          <th>{{ t('wan.priority') }}</th>
          <th v-if="mode === 'balance'">
            {{ t('wan.weight') }}
          </th>
          <th>Ping Check</th>
          <th>{{ t('wan.target') }}</th>
          <th>{{ t('wan.interval') }}</th>
          <th>{{ t('col.state') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="iface in props.wanIfaces"
          :key="iface"
        >
          <td><span class="mono">{{ iface }}</span></td>
          <td>
            <input
              v-model="form[iface].priority"
              class="num-input"
              inputmode="numeric"
              placeholder="—"
            >
          </td>
          <td v-if="mode === 'balance'">
            <input
              v-model="form[iface].weight"
              class="num-input"
              inputmode="numeric"
              min="1"
              max="100"
              :title="t('wan.weightHint')"
            >
          </td>
          <td>
            <label class="check-line">
              <input
                v-model="form[iface].pingEnabled"
                type="checkbox"
              >
            </label>
          </td>
          <td>
            <input
              v-model="form[iface].target"
              :disabled="!form[iface].pingEnabled"
            >
          </td>
          <td>
            <div class="inline-fields">
              <input
                v-model="form[iface].intervalS"
                class="num-input"
                inputmode="numeric"
                :disabled="!form[iface].pingEnabled"
                :title="t('wan.intervalHint')"
              >
              <span class="muted">{{ t('common.sec') }} /</span>
              <input
                v-model="form[iface].failThreshold"
                class="num-input"
                inputmode="numeric"
                :disabled="!form[iface].pingEnabled"
                :title="t('wan.thresholdHint')"
              >
            </div>
          </td>
          <td>
            <template v-if="form[iface].pingEnabled && status[iface] && status[iface].state">
              <span
                class="status-dot"
                :class="{
                  up: status[iface].state === 'ok',
                  warn: ['checking', 'unknown'].includes(status[iface].state),
                  err: status[iface].state === 'fail',
                }"
              />
              <span v-if="status[iface].state === 'ok' && status[iface].latency_ms !== null">
                {{ t('common.ms', { n: Math.round(status[iface].latency_ms) }) }}
              </span>
              <span v-else-if="status[iface].state === 'fail'">{{ t('wan.noLink') }}</span>
              <span
                v-else
                class="muted"
              >{{ t('wan.checking') }}</span>
            </template>
            <template v-else-if="status[iface] && status[iface].operstate">
              <span
                class="status-dot"
                :class="{
                  up: status[iface].operstate === 'up',
                  err: ['down', 'no-carrier'].includes(status[iface].operstate),
                }"
              />
              <span v-if="status[iface].operstate === 'up'">
                {{ (status[iface].ipv4 || [])[0] || t('wan.online') }}
              </span>
              <span v-else-if="status[iface].operstate === 'no-carrier'">{{ t('wan.noCarrier') }}</span>
              <span
                v-else-if="status[iface].operstate === 'down'"
                class="muted"
              >{{ t('wan.offState') }}</span>
              <span
                v-else
                class="muted"
              >—</span>
            </template>
            <span
              v-else
              class="muted"
            >{{ t('wan.offShort') }}</span>
          </td>
        </tr>
        <tr v-if="!props.wanIfaces.length">
          <td :colspan="mode === 'balance' ? 7 : 6">
            {{ t('wan.none') }}
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint-text table-hint">
      {{ t('wan.hint') }}
    </p>
  </div>
</template>
