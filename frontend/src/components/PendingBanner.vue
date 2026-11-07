<script setup>
import { t } from '../i18n'

defineProps({
  pending: { type: Object, required: true },
  countdown: { type: Number, required: true },
})

const emit = defineEmits(['confirm', 'rollback'])

function rollback() {
  if (confirm(t('pending.rollbackAsk'))) {
    emit('rollback')
  }
}
</script>

<template>
  <div class="card pending-banner">
    <div>
      <strong>{{ t('pending.title') }}</strong>
      {{ t('pending.body') }}
      <span class="countdown">{{ countdown }} {{ t('common.sec') }}</span>
      {{ t('pending.body2') }}
    </div>
    <div class="dialog-actions">
      <button
        class="btn"
        @click="rollback"
      >
        {{ t('pending.rollback') }}
      </button>
      <button
        class="btn primary"
        @click="$emit('confirm')"
      >
        {{ t('pending.confirm') }}
      </button>
    </div>
  </div>
</template>
