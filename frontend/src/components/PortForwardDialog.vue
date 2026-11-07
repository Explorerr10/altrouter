<script setup>
import { computed, reactive } from 'vue'
import { forwardFromForm, forwardToForm } from '../utils/rules'
import { t } from '../i18n'

const props = defineProps({
  initial: { type: Object, default: null },
  wanIfaces: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'save'])

const isNew = computed(() => !props.initial)
const form = reactive(forwardToForm(props.initial))

function submit() {
  emit('save', forwardFromForm(form))
}
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog wide">
      <h2>{{ isNew ? t('pf.new') : t('pf.edit', { p: form.port }) }}</h2>
      <form @submit.prevent="submit">
        <label>
          {{ t('pf.wanConn') }}
          <select v-model="form.wan">
            <option value="">
              {{ t('pf.allWan') }}
            </option>
            <option
              v-for="name in props.wanIfaces"
              :key="name"
              :value="name"
            >
              {{ name }}
            </option>
          </select>
        </label>
        <label>
          {{ t('common.proto') }}
          <select v-model="form.proto">
            <option value="tcp">
              TCP
            </option>
            <option value="udp">
              UDP
            </option>
            <option value="both">
              {{ t('fw.proto.both') }}
            </option>
          </select>
        </label>
        <label>
          {{ t('pf.extPort') }}
          <input
            v-model="form.port"
            placeholder="8080"
          >
        </label>
        <label>
          {{ t('pf.toIp') }}
          <input
            v-model="form.toIp"
            placeholder="192.168.10.50"
          >
        </label>
        <label>
          {{ t('pf.toPort') }}
          <input
            v-model="form.toPort"
            placeholder="80"
          >
        </label>
        <label>
          {{ t('common.comment') }}
          <input
            v-model="form.comment"
            :placeholder="t('pf.phComment')"
          >
        </label>
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
