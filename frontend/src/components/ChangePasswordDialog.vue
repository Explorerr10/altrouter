<script setup>
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { t } from '../i18n'

const emit = defineEmits(['close', 'changed'])
const auth = useAuthStore()

const oldPassword = ref('')
const newPassword = ref('')
const repeat = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (newPassword.value.length < 6) {
    error.value = t('pw.errShort')
    return
  }
  if (newPassword.value !== repeat.value) {
    error.value = t('pw.errMatch')
    return
  }
  busy.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    emit('changed')
  } catch (err) {
    error.value = err.message || t('pw.errFail')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog">
      <h2>{{ t('pw.title') }}</h2>
      <form @submit.prevent="submit">
        <label>
          {{ t('pw.old') }}
          <input
            v-model="oldPassword"
            type="password"
            autocomplete="current-password"
          >
        </label>
        <label>
          {{ t('pw.new') }}
          <input
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
          >
        </label>
        <label>
          {{ t('pw.repeat') }}
          <input
            v-model="repeat"
            type="password"
            autocomplete="new-password"
          >
        </label>
        <p
          v-if="error"
          class="form-error"
        >
          {{ error }}
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
            :disabled="busy"
          >
            {{ t('common.save') }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
