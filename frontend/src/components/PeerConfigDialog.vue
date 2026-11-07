<script setup>
import { computed, ref } from 'vue'
import QRCode from 'qrcode'
import { api } from '../api/client'
import { t } from '../i18n'

const props = defineProps({
  tunnel: { type: Object, required: true },
})

const emit = defineEmits(['close'])

const selected = ref(props.tunnel.peers[0]?.name ?? '')
const text = ref('')
const qr = ref('')
const error = ref('')
const loading = ref(false)

const peer = computed(() => props.tunnel.peers.find((item) => item.name === selected.value))

async function load() {
  error.value = ''
  text.value = ''
  qr.value = ''
  loading.value = true
  try {
    const name = encodeURIComponent(selected.value)
    const resp = await api.get(
      `/network/vpn/wireguard/${encodeURIComponent(props.tunnel.id)}/peer/${name}/config`,
    )
    text.value = typeof resp === 'string' ? resp : String(resp)
    qr.value = await QRCode.toDataURL(text.value, { width: 280, errorCorrectionLevel: 'L' })
  } catch (err) {
    error.value = err.message || t('wg.cfgErr')
  } finally {
    loading.value = false
  }
}

function download() {
  const blob = new Blob([text.value], { type: 'text/plain' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `wg-${props.tunnel.id}-${selected.value}.conf`
  link.click()
  URL.revokeObjectURL(link.href)
}
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog">
      <h2>{{ t('wg.clientCfg', { n: props.tunnel.name }) }}</h2>
      <label>
        {{ t('wg.peer') }}
        <select v-model="selected">
          <option
            v-for="item in props.tunnel.peers"
            :key="item.name"
            :value="item.name"
          >
            {{ item.name }}
          </option>
        </select>
      </label>
      <div class="dialog-actions">
        <button
          class="btn small"
          :disabled="!selected || loading"
          @click="load"
        >
          {{ t('common.show') }}
        </button>
        <template v-if="text">
          <button
            class="btn small"
            @click="download"
          >
            {{ t('wg.download') }}
          </button>
        </template>
      </div>
      <p
        v-if="error"
        class="form-error"
      >
        {{ error }}
      </p>
      <p
        v-if="!peer?.private_key && selected"
        class="hint-text"
      >
        {{ t('wg.noKeyHint') }}
      </p>
      <template v-if="text">
        <pre class="config-text mono">{{ text }}</pre>
        <img
          v-if="qr"
          :src="qr"
          :alt="t('wg.qrAlt')"
          class="qr-image"
        >
      </template>
      <div class="dialog-actions">
        <button
          class="btn"
          @click="emit('close')"
        >
          {{ t('common.close') }}
        </button>
      </div>
    </div>
  </div>
</template>
