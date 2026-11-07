<script setup>
import { computed, reactive } from 'vue'
import { ruleFromForm, ruleToForm } from '../utils/rules'
import { t } from '../i18n'

const props = defineProps({
  initial: { type: Object, default: null },
  zones: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'save'])

const isNew = computed(() => !props.initial)
const form = reactive(ruleToForm(props.initial))
const portsLocked = computed(() => form.proto === 'any')

function submit() {
  emit('save', ruleFromForm(form))
}
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog">
      <h2>{{ isNew ? t('fw.newRule') : t('fw.rule', { n: props.initial?.comment || t('fw.unnamed') }) }}</h2>
      <form @submit.prevent="submit">
        <div class="form-grid">
          <label>
            {{ t('fw.direction') }}
            <select v-model="form.direction">
              <option value="forward">
                {{ t('fw.dir.forwardOpt') }}
              </option>
              <option value="input">
                {{ t('fw.dir.inputOpt') }}
              </option>
            </select>
          </label>
          <label>
            {{ t('fw.srcZone') }}
            <select v-model="form.zone">
              <option
                v-for="zone in props.zones"
                :key="zone.value"
                :value="zone.value"
              >
                {{ zone.label }}
              </option>
            </select>
          </label>
          <label>
            {{ t('common.proto') }}
            <select v-model="form.proto">
              <option value="any">
                {{ t('fw.proto.any') }}
              </option>
              <option value="tcp">
                TCP
              </option>
              <option value="udp">
                UDP
              </option>
            </select>
          </label>
          <label>
            {{ t('fw.action') }}
            <select v-model="form.action">
              <option value="allow">
                {{ t('fw.action.allow') }}
              </option>
              <option value="drop">
                {{ t('fw.action.drop') }}
              </option>
            </select>
          </label>
        </div>
        <div class="form-grid">
          <label>
            {{ t('fw.srcIp') }}
            <input
              v-model="form.srcIp"
              placeholder="192.168.10.0/24"
            >
          </label>
          <label>
            {{ t('fw.srcPort') }}
            <input
              v-model="form.srcPort"
              :disabled="portsLocked"
              placeholder="8000-9000"
            >
          </label>
          <label>
            {{ t('fw.dstIp') }}
            <input
              v-model="form.dstIp"
              placeholder="192.168.10.50"
            >
          </label>
          <label>
            {{ t('fw.dstPort') }}
            <input
              v-model="form.dstPort"
              :disabled="portsLocked"
              placeholder="443"
            >
          </label>
        </div>
        <label>
          {{ t('common.comment') }}
          <input
            v-model="form.comment"
            :placeholder="t('fw.phComment')"
          >
        </label>
        <p class="hint-text">
          {{ t('fw.hint2') }}
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
