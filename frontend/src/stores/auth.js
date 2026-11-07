import { defineStore } from 'pinia'
import { api } from '../api/client'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
  }),
  actions: {
    async login(username, password) {
      this.user = await api.post('/auth/login', { username, password })
    },
    async fetchMe() {
      try {
        this.user = await api.get('/auth/me')
        return true
      } catch {
        this.user = null
        return false
      }
    },
    async logout() {
      try {
        await api.post('/auth/logout')
      } catch {
        this.user = null
      }
      this.user = null
    },
    async changePassword(oldPassword, newPassword) {
      await api.post('/auth/password', {
        old_password: oldPassword,
        new_password: newPassword,
      })
    },
  },
})
