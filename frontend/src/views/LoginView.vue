<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { t } from '../i18n'
import LangSwitch from '../components/LangSwitch.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const username = ref('admin')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    await auth.login(username.value, password.value)
    const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.push(target)
  } catch (err) {
    error.value = err.message || t('login.error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-lang">
      <LangSwitch />
    </div>
    <form
      class="card login-card"
      @submit.prevent="submit"
    >
      <div class="brand login-brand">
        AltRouter
      </div>
      <label>
        {{ t('login.user') }}
        <input
          v-model="username"
          type="text"
          autocomplete="username"
        >
      </label>
      <label>
        {{ t('login.password') }}
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
        >
      </label>
      <p
        v-if="error"
        class="form-error"
      >
        {{ error }}
      </p>
      <button
        class="btn primary block"
        type="submit"
        :disabled="busy"
      >
        {{ t('login.submit') }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login-lang {
  position: fixed;
  top: 16px;
  right: 16px;
}
</style>
