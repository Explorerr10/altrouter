<script setup>
import { computed, reactive } from 'vue'
import { api } from '../api/client'
import { emptyPeerForm, ifaceFromForm, ifaceToForm } from '../utils/wireguard'
import { t } from '../i18n'

const props = defineProps({
  initial: { type: Object, default: null },
  error: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'save'])

const isNew = computed(() => !props.initial)
const form = reactive(ifaceToForm(props.initial))
const routeModes = ['none', 'all', 'devices']

function addPeer() {
  form.peers.push(emptyPeerForm())
}

function removePeer(index) {
  form.peers.splice(index, 1)
}

async function generateKeys(target) {
  const pair = await api.get('/network/vpn/keypair')
  target.privateKey = pair.private_key
  target.publicKey = pair.public_key
}

function submit() {
  emit('save', ifaceFromForm(form))
}
</script>

<template>
  <div
    class="overlay"
    @click.self="emit('close')"
  >
    <div class="card dialog">
      <h2>{{ isNew ? t('wg.new') : t('wg.edit', { n: form.name }) }}</h2>
      <form @submit.prevent="submit">
        <div class="form-grid">
          <label>
            {{ t('common.name') }}
            <input
              v-model="form.name"
              :placeholder="t('wg.phName')"
            >
          </label>
          <label>
            {{ t('wg.idLabel') }}{{ isNew ? '' : t('wg.idFixed') }}
            <input
              v-model="form.id"
              :disabled="!isNew"
              placeholder="home"
              class="mono"
            >
          </label>
        </div>
        <div class="form-grid">
          <label>
            {{ t('wg.addrInTunnel') }}
            <input
              v-model="form.address"
              placeholder="10.9.0.1/24"
              class="mono"
            >
          </label>
          <label>
            {{ t('wg.listenPort') }}
            <input
              v-model="form.listenPort"
              placeholder="51820"
              class="mono"
            >
          </label>
          <label>
            {{ t('common.mtuDefault') }}
            <input
              v-model="form.mtu"
              placeholder="1420"
            >
          </label>
        </div>
        <div class="form-grid">
          <label>
            {{ t('wg.endpoint') }}
            <input
              v-model="form.endpoint"
              placeholder="vpn.example.com"
            >
          </label>
          <label>
            {{ t('wg.routeMode') }}
            <select v-model="form.routeMode">
              <option
                v-for="mode in routeModes"
                :key="mode"
                :value="mode"
              >
                {{ t('wg.route.' + mode) }}
              </option>
            </select>
          </label>
          <label v-if="form.routeMode !== 'none'">
            {{ t('wg.priority') }}
            <input
              v-model="form.priority"
              class="num-input"
              inputmode="numeric"
            >
          </label>
        </div>
        <label v-if="form.routeMode === 'devices'">
          {{ t('wg.devices') }}
          <input
            v-model="form.devices"
            placeholder="192.168.10.55, 192.168.10.60/32"
            class="mono"
          >
        </label>
        <label>
          {{ t('wg.privKey') }}
          <div class="inline-fields">
            <input
              v-model="form.privateKey"
              class="mono"
              :placeholder="t('wg.phGen')"
            >
            <button
              type="button"
              class="btn"
              @click="generateKeys(form)"
            >
              {{ t('wg.generate') }}
            </button>
          </div>
        </label>
        <p
          v-if="form.publicKey"
          class="hint-text"
        >
          {{ t('wg.pubKey', { k: form.publicKey }) }}
        </p>

        <h3>{{ t('wg.peers') }}</h3>
        <div
          v-for="(peer, index) in form.peers"
          :key="index"
          class="peer-editor"
        >
          <div class="form-grid">
            <label>
              {{ t('wg.peerName') }}
              <input
                v-model="peer.name"
                :placeholder="t('wg.phPeerName')"
              >
            </label>
            <label>
              Allowed IP
              <input
                v-model="peer.allowedIps"
                placeholder="10.9.0.2/32"
                class="mono"
              >
            </label>
            <label>
              {{ t('wg.peerEndpoint') }}
              <input
                v-model="peer.endpoint"
                placeholder="peer.example.com:51820"
              >
            </label>
          </div>
          <div class="form-grid">
            <label>
              {{ t('wg.peerPub') }}
              <input
                v-model="peer.publicKey"
                class="mono"
                :placeholder="t('wg.phOwn')"
              >
            </label>
            <label>
              {{ t('wg.peerPriv') }}
              <div class="inline-fields">
                <input
                  v-model="peer.privateKey"
                  class="mono"
                  :placeholder="t('wg.phClient')"
                >
                <button
                  type="button"
                  class="btn"
                  @click="generateKeys(peer)"
                >
                  {{ t('wg.generate') }}
                </button>
              </div>
            </label>
          </div>
          <div class="form-grid">
            <label>
              {{ t('common.comment') }}
              <input
                v-model="peer.comment"
                :placeholder="t('wg.phPeerComment')"
              >
            </label>
            <label>
              {{ t('wg.keepalive') }}
              <input
                v-model="peer.keepalive"
                placeholder="25"
                class="num-input"
              >
            </label>
          </div>
          <button
            type="button"
            class="btn small"
            @click="removePeer(index)"
          >
            {{ t('wg.removePeer') }}
          </button>
        </div>
        <button
          type="button"
          class="btn small"
          @click="addPeer"
        >
          {{ t('wg.addPeer') }}
        </button>

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
