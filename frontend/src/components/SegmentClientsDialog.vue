<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api/client'
import { emptyReservation, ipInCidr } from '../utils/segments'
import { t } from '../i18n'

const props = defineProps({
  segment: { type: Object, required: true },
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'save'])

const reservations = reactive((props.segment.reservations ?? []).map((r) => ({ ...r })))
const clients = ref([])
const localError = ref('')

const reservedMacs = computed(
  () => new Set(reservations.map((r) => String(r.mac ?? '').toLowerCase())),
)

onMounted(async () => {
  try {
    const all = await api.get('/clients')
    clients.value = all.filter((c) => ipInCidr(c.ip, props.segment.address))
  } catch (err) {
    localError.value = err.message || t('seg.loadErr')
  }
})

function register(client) {  if (reservedMacs.value.has(String(client.mac ?? '').toLowerCase())) {
    return
  }
  reservations.push({
    mac: client.mac ?? '',
    ip: client.ip ?? '',
    hostname: client.hostname ?? '',
    comment: '',
  })
}

function addReservation() {
  localError.value = ''
  reservations.push(emptyReservation())
}

function removeReservation(index) {
  reservations.splice(index, 1)
}

function submit() {
  const seen = new Set()
  const list = []
  for (const res of reservations) {
    const mac = String(res.mac ?? '').trim().toLowerCase()
    const ip = String(res.ip ?? '').trim()
    if (!mac || !ip) {
      continue
    }
    if (seen.has(mac)) {
      localError.value = t('seg.dupMac', { m: mac })
      return
    }
    seen.add(mac)
    list.push({
      mac,
      ip,
      hostname: String(res.hostname ?? '').trim() || null,
      comment: String(res.comment ?? '').trim() || null,
    })
  }
  localError.value = ''
  emit('save', { ...props.segment, reservations: list })
}
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog wide">
      <h2>{{ t('home.clients') }} <span class="mono">arbr-{{ segment.id }}</span></h2>
      <p class="hint-text">
        {{ t('seg.subnetIs', { a: segment.address }) }}
        {{ t('seg.reservationHint') }}
      </p>
      <div>
        <div class="ports-title">
          {{ t('seg.resList') }}
        </div>
        <table class="mini-table">
          <thead>
            <tr>
              <th>MAC</th>
              <th>IP</th>
              <th>{{ t('col.name') }}</th>
              <th>{{ t('common.comment') }}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(res, index) in reservations"
              :key="index"
            >
              <td>
                <input
                  v-model="res.mac"
                  class="w-mac"
                  placeholder="11:22:33:44:55:66"
                >
              </td>
              <td>
                <input
                  v-model="res.ip"
                  class="w-ip"
                  placeholder="192.168.10.7"
                >
              </td>
              <td>
                <input
                  v-model="res.hostname"
                  class="w-name"
                  placeholder="nas"
                >
              </td>
              <td>
                <input
                  v-model="res.comment"
                  :placeholder="t('seg.phComment')"
                >
              </td>
              <td>
                <button
                  type="button"
                  class="btn small"
                  @click="removeReservation(index)"
                >
                  {{ t('common.delete') }}
                </button>
              </td>
            </tr>
            <tr v-if="!reservations.length">
              <td colspan="5">
                {{ t('seg.noReservations') }}
              </td>
            </tr>
          </tbody>
        </table>
        <button
          type="button"
          class="btn small"
          @click="addReservation"
        >
          {{ t('seg.addAddress') }}
        </button>
      </div>
      <div>
        <div class="ports-title">
          {{ t('seg.dhcpClients') }}
        </div>
        <table class="mini-table">
          <thead>
            <tr>
              <th>{{ t('col.name') }}</th>
              <th>MAC</th>
              <th>IP</th>
              <th>{{ t('col.status') }}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="client in clients"
              :key="client.mac + client.ip"
            >
              <td>{{ client.hostname || '—' }}</td>
              <td>
                <span class="mono">{{ client.mac }}</span>
              </td>
              <td>
                <span class="mono">{{ client.ip }}</span>
              </td>
              <td>{{ client.active ? t('common.yes') : t('common.no') }}</td>
              <td>
                <button
                  type="button"
                  class="btn small"
                  :disabled="reservedMacs.has(String(client.mac ?? '').toLowerCase())"
                  :title="reservedMacs.has(String(client.mac ?? '').toLowerCase())
                    ? t('seg.macRegistered') : ''"
                  @click="register(client)"
                >
                  {{ t('seg.register') }}
                </button>
              </td>
            </tr>
            <tr v-if="!clients.length">
              <td colspan="5">
                {{ t('seg.noClients') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p
        v-if="props.error || localError"
        class="form-error"
      >
        {{ props.error || localError }}
      </p>
      <div class="dialog-actions">
        <button
          type="button"
          class="btn"
          @click="emit('close')"
        >
          {{ t('common.cancel') }}
        </button>
        <button
          type="button"
          class="btn primary"
          :disabled="props.busy"
          @click="submit"
        >
          {{ t('common.apply') }}
        </button>
      </div>
    </div>
  </div>
</template>
