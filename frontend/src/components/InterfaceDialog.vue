<script setup>
import { reactive, watch } from 'vue'
import { fromForm, toForm } from '../utils/ifaces'
import { t } from '../i18n'

const props = defineProps({
  name: { type: String, required: true },
  initial: { type: Object, default: null },
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'save'])

const form = reactive(toForm({ ...(props.initial ?? {}), name: props.name }))

watch(
  () => form.role,
  () => {
    if (form.role === 'lan') {
      form.ipv4 = 'static'
    }
  },
)
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog wide">
      <h2>{{ t('iface.title', { n: props.name }) }}</h2>
      <form @submit.prevent="emit('save', fromForm(form))">
        <label>
          {{ t('iface.role') }}
          <select v-model="form.role">
            <option value="wan">
              {{ t('iface.wan') }}
            </option>
            <option value="lan">
              {{ t('iface.lan') }}
            </option>
            <option value="off">
              {{ t('role.off') }}
            </option>
          </select>
        </label>
        <template v-if="form.role !== 'off'">
          <label v-if="form.role === 'wan'">
            {{ t('iface.ipv4Method') }}
            <select v-model="form.ipv4">
              <option value="dhcp">
                {{ t('iface.dhcp') }}
              </option>
              <option value="static">
                {{ t('iface.static') }}
              </option>
              <option value="pppoe">
                {{ t('iface.pppoe') }}
              </option>
            </select>
          </label>
          <template v-if="form.ipv4 === 'pppoe'">
            <label>
              {{ t('iface.pppoeUser') }}
              <input
                v-model="form.pppoe_username"
                placeholder="user@provider"
              >
            </label>
            <label>
              {{ t('iface.pppoePass') }}
              <input
                v-model="form.pppoe_password"
                type="password"
              >
            </label>
          </template>
          <template v-if="form.ipv4 === 'static'">
            <label>
              {{ t('iface.address') }}
              <input
                v-model="form.address"
                placeholder="192.168.10.1/24"
              >
            </label>
            <label v-if="form.role === 'wan'">
              {{ t('iface.gateway') }}
              <input
                v-model="form.gateway"
                placeholder="192.168.10.1"
              >
            </label>
          </template>
          <label v-if="form.role === 'wan'">
            {{ t('iface.dns') }}
            <input
              v-model="form.dnsText"
              placeholder="1.1.1.1, 8.8.8.8"
            >
          </label>
          <label v-if="form.role === 'wan'">
            {{ t('iface.mac') }}
            <input
              v-model="form.mac"
              class="mono"
              placeholder="aa:bb:cc:dd:ee:ff"
            >
          </label>
          <label>
            {{ t('common.mtuDefault') }}
            <input
              v-model="form.mtu"
              inputmode="numeric"
              placeholder="1500"
            >
          </label>
        </template>
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
