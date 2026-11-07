<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { segFromForm, segToForm, slugifyId } from '../utils/segments'
import { t } from '../i18n'

const props = defineProps({
  initial: { type: Object, default: null },
  freePorts: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'save'])

const isNew = computed(() => !props.initial)
const form = reactive(segToForm(props.initial))
const idTouched = ref(false)

watch(
  () => form.name,
  () => {
    if (isNew.value && !idTouched.value) {
      form.id = slugifyId(form.name)
    }
  },
)

function onIdInput() {
  idTouched.value = true
}

function togglePort(name) {
  const pos = form.ports.indexOf(name)
  if (pos >= 0) {
    form.ports.splice(pos, 1)
  } else {
    form.ports.push(name)
  }
}

function submit() {
  emit('save', segFromForm(form))
}
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog wide">
      <h2>{{ isNew ? t('seg.new') : t('seg.edit', { n: form.name }) }}</h2>
      <form @submit.prevent="submit">
        <label>
          {{ t('common.name') }}
          <input
            v-model="form.name"
            :placeholder="t('home.seg')"
          >
        </label>
        <label>
          {{ t('seg.idLabel') }}
          <input
            v-model="form.id"
            :disabled="!isNew"
            placeholder="home"
            @input="onIdInput"
          >
        </label>
        <div>
          <div class="ports-title">
            {{ t('seg.lanPorts') }}
          </div>
          <label
            v-for="port in freePorts"
            :key="port"
            class="check-line"
          >
            <input
              type="checkbox"
              :checked="form.ports.includes(port)"
              @change="togglePort(port)"
            >
            <span class="mono">{{ port }}</span>
          </label>
          <p
            v-if="!freePorts.length"
            class="hint-text"
          >
            {{ t('seg.noFree') }}
          </p>
        </div>
        <label>
          {{ t('seg.addr') }}
          <input
            v-model="form.address"
            placeholder="192.168.10.1/24"
          >
        </label>
        <label class="check-line">
          <input
            v-model="form.dhcpEnabled"
            type="checkbox"
          >
          <span>{{ t('seg.dhcpLabel') }}</span>
        </label>
        <template v-if="form.dhcpEnabled">
          <div class="form-grid">
            <label>
              {{ t('seg.poolStart') }}
              <input
                v-model="form.poolStart"
                placeholder="192.168.10.50"
              >
            </label>
            <label>
              {{ t('seg.poolEnd') }}
              <input
                v-model="form.poolEnd"
                placeholder="192.168.10.150"
              >
            </label>
            <label>
              {{ t('seg.lease') }}
              <input
                v-model="form.leaseHours"
                inputmode="numeric"
                placeholder="12"
              >
            </label>
            <label>
              {{ t('seg.dns') }}
              <input
                v-model="form.dnsText"
                placeholder="1.1.1.1, 8.8.8.8"
              >
            </label>
          </div>
        </template>
        <p class="hint-text">
          {{ t('seg.resHint') }}
        </p>
        <p
          v-if="props.error"
          class="form-error"
        >
          {{ props.error }}
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
            type="submit"
            class="btn primary"
            :disabled="props.busy"
          >
            {{ t('common.apply') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
