<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { t } from '../i18n'
import ChangePasswordDialog from './ChangePasswordDialog.vue'
import LangSwitch from './LangSwitch.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const showPasswordDialog = ref(false)

const menu = [
  { path: '/', key: 'nav.dashboard' },
  { path: '/internet', key: 'nav.internet' },
  { path: '/home-network', key: 'nav.home' },
  { path: '/rules', key: 'nav.rules' },
  { path: '/vpn', key: 'nav.vpn' },
  { path: '/management', key: 'nav.management' },
]

const title = computed(() => (route.meta.titleKey ? t(route.meta.titleKey) : ''))

async function logout() {
  await auth.logout()
  router.push('/login')
}

async function onPasswordChanged() {
  showPasswordDialog.value = false
  await auth.fetchMe()
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        AltRouter
      </div>
      <nav class="menu">
        <router-link
          v-for="item in menu"
          :key="item.path"
          :to="item.path"
          class="menu-item"
        >
          {{ t(item.key) }}
        </router-link>
      </nav>
    </aside>
    <div class="main">
      <header class="topbar">
        <div class="topbar-title">
          {{ title }}
        </div>
        <div class="topbar-right">
          <LangSwitch />
          <template v-if="auth.user">
            <span
              v-if="auth.user.default_password"
              class="warn-badge"
            >
              {{ t('app.defaultPassword') }}
            </span>
            <span class="user-chip">{{ auth.user.username }}</span>
            <button
              class="btn small"
              @click="showPasswordDialog = true"
            >
              {{ t('app.changePassword') }}
            </button>
            <button
              class="btn small"
              @click="logout"
            >
              {{ t('app.logout') }}
            </button>
          </template>
        </div>
      </header>
      <main class="content">
        <router-view />
      </main>
    </div>
    <ChangePasswordDialog
      v-if="showPasswordDialog"
      @close="showPasswordDialog = false"
      @changed="onPasswordChanged"
    />
  </div>
</template>
