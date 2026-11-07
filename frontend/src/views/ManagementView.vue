<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { t } from '../i18n'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

const users = ref([])
const newUser = ref({ username: '', password: '', role: 'viewer' })
const usersErr = ref('')

const backupBusy = ref(false)
const backupMsg = ref('')

const journal = ref([])
const journalErr = ref('')
const journalOpen = ref(true)

const diag = ref({ host: '', count: 4, iface: '', filter: '', seconds: 10 })
const diagOut = ref('')
const diagErr = ref('')
const diagBusy = ref(false)

const logUnit = ref('altrouter')
const logLines = ref(200)
const logOut = ref('')
const logErr = ref('')
const logBusy = ref(false)

const ssh = ref({ active: false, enabled: false, port: null, allow_subnet: null, password_auth: true })
const sshCfg = ref({ port: 22, allow: '', pw: true })
const segments = ref([])
const sshUsers = ref([])
const sshKeyUser = ref('')
const sshKeys = ref([])
const sshKeyNew = ref('')
const tls = ref({})
const tlsCert = ref('')
const tlsKey = ref('')
const tlsHosts = ref('')
const tlsMsg = ref('')
const mgmtOnly = ref(false)
const mgmtIface = ref('')
const accessErr = ref('')

const updates = ref(null)
const updBusy = ref(false)
const updErr = ref('')
const updOut = ref('')

const powerErr = ref('')

async function loadUsers() {
  if (!isAdmin.value) return
  try {
    users.value = await api.get('/system/users')
  } catch (e) {
    usersErr.value = e.message
  }
}

async function addUser() {
  usersErr.value = ''
  try {
    await api.post('/system/users', newUser.value)
    newUser.value = { username: '', password: '', role: 'viewer' }
    await loadUsers()
  } catch (e) {
    usersErr.value = e.message
  }
}

async function changeUserPassword(u) {
  const password = prompt(t('mgmt.newPassAsk', { n: u.username }))
  if (!password) return
  usersErr.value = ''
  try {
    await api.put(`/system/users/${u.username}`, { password })
  } catch (e) {
    usersErr.value = e.message
  }
}

async function deleteUser(u) {
  if (!confirm(t('mgmt.delUserAsk', { n: u.username }))) return
  usersErr.value = ''
  try {
    await api.del(`/system/users/${u.username}`)
    await loadUsers()
  } catch (e) {
    usersErr.value = e.message
  }
}

async function downloadBackup() {
  backupBusy.value = true
  backupMsg.value = ''
  try {
    const resp = await fetch('/api/system/backup', { credentials: 'same-origin' })
    if (!resp.ok) throw new Error(t('mgmt.backupErr'))
    const name =
      (resp.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] ||
      'altrouter-backup.tar.gz'
    const url = URL.createObjectURL(await resp.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.click()
    URL.revokeObjectURL(url)
    backupMsg.value = t('mgmt.backupOk')
  } catch (e) {
    backupMsg.value = e.message
  } finally {
    backupBusy.value = false
  }
}

async function uploadBackup(event) {
  const file = event.target.files[0]
  if (!file) return
  backupBusy.value = true
  backupMsg.value = ''
  try {
    const resp = await fetch('/api/system/backup', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/gzip' },
      body: await file.arrayBuffer(),
    })
    const body = await resp.json()
    if (!resp.ok) throw new Error(body.detail || t('mgmt.restoreErr'))
    backupMsg.value = t('mgmt.restoreOk')
  } catch (e) {
    backupMsg.value = e.message
  } finally {
    backupBusy.value = false
    event.target.value = ''
  }
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString()
}

async function loadJournal() {
  try {
    journal.value = await api.get('/system/journal?limit=50')
  } catch (e) {
    journalErr.value = e.message
  }
}

async function runDiag(kind) {
  diagBusy.value = true
  diagErr.value = ''
  diagOut.value = ''
  try {
    const path = { ping: '/system/diag/ping', traceroute: '/system/diag/traceroute', tcpdump: '/system/diag/tcpdump' }[kind]
    const payload =
      kind === 'tcpdump'
        ? { iface: diag.value.iface, filter: diag.value.filter, seconds: diag.value.seconds }
        : kind === 'ping'
          ? { host: diag.value.host, count: diag.value.count }
          : { host: diag.value.host }
    diagOut.value = (await api.post(path, payload)).output
  } catch (e) {
    diagErr.value = e.message
  } finally {
    diagBusy.value = false
  }
}

async function loadLog() {
  logBusy.value = true
  logErr.value = ''
  try {
    logOut.value = (
      await api.get(`/system/logs?unit=${logUnit.value}&lines=${logLines.value}`)
    ).output
  } catch (e) {
    logErr.value = e.message
  } finally {
    logBusy.value = false
  }
}

function netOf(address) {
  const [ip, bitsRaw] = address.split('/')
  const bits = bitsRaw === undefined ? 32 : Number(bitsRaw)
  const o = ip.split('.').map(Number)
  const full = ((o[0] << 24) | (o[1] << 16) | (o[2] << 8) | o[3]) >>> 0
  const net = bits === 0 ? 0 : (full & (0xffffffff << (32 - bits))) >>> 0
  return `${[net >>> 24, (net >>> 16) & 255, (net >>> 8) & 255, net & 255].join('.')}/${bits}`
}

async function loadAccess() {
  try {
    ssh.value = await api.get('/system/ssh')
    sshCfg.value.port = ssh.value.port || 22
    sshCfg.value.allow = ssh.value.allow_subnet || ''
    sshCfg.value.pw = ssh.value.password_auth !== false
    tls.value = await api.get('/system/tls')
    const a = await api.get('/system/access')
    mgmtOnly.value = a.management_only
    mgmtIface.value = a.iface
    if (isAdmin.value) {
      const snap = await api.get('/network/interfaces/config')
      segments.value = (snap.segments || []).map((s) => ({
        id: s.id,
        name: s.name,
        subnet: netOf(s.address),
      }))
      sshUsers.value = await api.get('/system/ssh/users')
      if (!sshUsers.value.some((u) => u.username === sshKeyUser.value)) {
        sshKeyUser.value = sshUsers.value[0]?.username || ''
      }
      await loadSshKeys()
    }
  } catch (e) {
    accessErr.value = e.message
  }
}

async function loadSshKeys() {
  sshKeys.value = sshKeyUser.value
    ? await api.get(`/system/ssh/keys?user=${sshKeyUser.value}`)
    : []
}

async function applySshConfig() {
  const warn = sshCfg.value.pw ? '' : t('mgmt.sshWarn')
  if (!confirm(`${t('mgmt.sshAsk')}${warn}`)) return
  accessErr.value = ''
  try {
    ssh.value = await api.put('/system/ssh/config', {
      port: sshCfg.value.port,
      allow_subnet: sshCfg.value.allow || null,
      password_auth: sshCfg.value.pw,
    })
  } catch (e) {
    accessErr.value = e.message
  }
}

function pickKeyFile(event) {
  const file = event.target.files[0]
  if (!file) return
  file.text().then((text) => {
    sshKeyNew.value = text.trim()
  })
  event.target.value = ''
}

async function addSshKey() {
  accessErr.value = ''
  try {
    await api.put('/system/ssh/keys', { user: sshKeyUser.value, key: sshKeyNew.value })
    sshKeyNew.value = ''
    await loadSshKeys()
  } catch (e) {
    accessErr.value = e.message
  }
}

async function delSshKey(k) {
  if (!confirm(t('mgmt.delKeyAsk', { f: k.fingerprint }))) return
  accessErr.value = ''
  try {
    await api.del(`/system/ssh/keys/${sshKeyUser.value}/${k.index}`)
    await loadSshKeys()
  } catch (e) {
    accessErr.value = e.message
  }
}

async function toggleSsh() {
  const enable = !ssh.value.enabled
  if (!confirm(enable ? t('mgmt.sshEnableAsk') : t('mgmt.sshDisableAsk'))) return
  accessErr.value = ''
  try {
    ssh.value = await api.put('/system/ssh', { enabled: enable })
  } catch (e) {
    accessErr.value = e.message
  }
}

async function applyTls() {
  tlsMsg.value = ''
  try {
    await api.put('/system/tls', { cert: tlsCert.value, key: tlsKey.value })
    tlsCert.value = ''
    tlsKey.value = ''
    tls.value = await api.get('/system/tls')
    tlsMsg.value = t('mgmt.tlsOk')
  } catch (e) {
    tlsMsg.value = e.message
  }
}

async function generateTls() {
  tlsMsg.value = ''
  try {
    await api.post('/system/tls/generate', {
      hosts: tlsHosts.value.split(/[\s,;]+/).filter(Boolean),
    })
    tls.value = await api.get('/system/tls')
    tlsMsg.value = t('mgmt.tlsGenOk')
  } catch (e) {
    tlsMsg.value = e.message
  }
}

async function saveAccess() {
  if (mgmtOnly.value && !confirm(t('mgmt.accessAsk'))) return
  accessErr.value = ''
  try {
    await api.put('/system/access', { management_only: mgmtOnly.value })
  } catch (e) {
    accessErr.value = e.message
  }
}

async function checkUpdates() {
  updBusy.value = true
  updErr.value = ''
  try {
    updates.value = (await api.get('/system/updates')).count
  } catch (e) {
    updErr.value = e.message
  } finally {
    updBusy.value = false
  }
}

async function applyUpdates() {
  if (!confirm(t('mgmt.updAsk'))) return
  updBusy.value = true
  updErr.value = ''
  try {
    updOut.value = (await api.post('/system/updates/apply')).output
    updates.value = 0
  } catch (e) {
    updErr.value = e.message
  } finally {
    updBusy.value = false
  }
}

async function powerAction(action) {
  if (!confirm(action === 'reboot' ? t('mgmt.rebootAsk') : t('mgmt.offAsk'))) return
  powerErr.value = ''
  try {
    await api.post('/system/power', { action })
  } catch (e) {
    powerErr.value = e.message
  }
}

onMounted(() => {
  loadUsers()
  loadJournal()
  loadAccess()
})
</script>

<template>
  <div class="management">
    <div class="card">
      <h3>{{ t('mgmt.users') }}</h3>
      <p
        v-if="!isAdmin"
        class="muted"
      >
        {{ t('mgmt.adminOnly') }}
      </p>
      <template v-else>
        <table
          v-if="users.length"
          class="data"
        >
          <thead>
            <tr>
              <th>{{ t('mgmt.user') }}</th>
              <th>{{ t('mgmt.role') }}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="u in users"
              :key="u.username"
            >
              <td>{{ u.username }}</td>
              <td>{{ u.role === 'admin' ? t('mgmt.roleAdmin') : t('mgmt.roleView') }}</td>
              <td>
                <button
                  class="btn small"
                  @click="changeUserPassword(u)"
                >
                  {{ t('mgmt.password') }}
                </button>
                <button
                  class="btn small"
                  @click="deleteUser(u)"
                >
                  {{ t('common.delete') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="row">
          <input
            v-model="newUser.username"
            :placeholder="t('mgmt.phUser')"
          >
          <input
            v-model="newUser.password"
            type="password"
            :placeholder="t('mgmt.phPass')"
          >
          <select v-model="newUser.role">
            <option value="viewer">
              {{ t('mgmt.roleView') }}
            </option>
            <option value="admin">
              {{ t('mgmt.roleAdmin') }}
            </option>
          </select>
          <button
            class="btn primary"
            @click="addUser"
          >
            {{ t('common.add') }}
          </button>
        </div>
        <p
          v-if="usersErr"
          class="form-error"
        >
          {{ usersErr }}
        </p>
      </template>
    </div>

    <div
      v-if="isAdmin"
      class="card"
    >
      <h3>{{ t('mgmt.backup') }}</h3>
      <p class="muted">
        {{ t('mgmt.backupHint') }}
      </p>
      <div class="row">
        <button
          class="btn primary"
          :disabled="backupBusy"
          @click="downloadBackup"
        >
          {{ t('mgmt.download') }}
        </button>
        <label
          class="btn"
          :class="{ disabled: backupBusy }"
        >
          {{ t('mgmt.upload') }}
          <input
            type="file"
            accept=".gz,.tgz,.tar.gz"
            hidden
            @change="uploadBackup"
          >
        </label>
      </div>
      <p
        v-if="backupMsg"
        class="muted"
      >
        {{ backupMsg }}
      </p>
    </div>

    <div class="card">
      <h3>{{ t('mgmt.diag') }}</h3>
      <div class="row">
        <input
          v-model="diag.host"
          :placeholder="t('mgmt.phHost')"
        >
        <select v-model="diag.count">
          <option
            v-for="n in 10"
            :key="n"
            :value="n"
          >
            {{ t('mgmt.packets', { n }) }}
          </option>
        </select>
        <button
          class="btn"
          :disabled="diagBusy || !diag.host"
          @click="runDiag('ping')"
        >
          Ping
        </button>
        <button
          class="btn"
          :disabled="diagBusy || !diag.host"
          @click="runDiag('traceroute')"
        >
          Traceroute
        </button>
      </div>
      <div
        v-if="isAdmin"
        class="row"
      >
        <input
          v-model="diag.iface"
          :placeholder="t('mgmt.phIface')"
          class="iface"
        >
        <input
          v-model="diag.filter"
          :placeholder="t('mgmt.phFilter')"
          class="filter"
        >
        <select v-model="diag.seconds">
          <option
            v-for="s in [5, 10, 20, 30, 60]"
            :key="s"
            :value="s"
          >
            {{ t('mgmt.seconds', { s }) }}
          </option>
        </select>
        <button
          class="btn"
          :disabled="diagBusy || !diag.iface"
          @click="runDiag('tcpdump')"
        >
          {{ t('mgmt.capture') }}
        </button>
      </div>
      <p
        v-if="diagErr"
        class="form-error"
      >
        {{ diagErr }}
      </p>
      <pre
        v-if="diagOut"
        class="out"
      >{{ diagOut }}</pre>
    </div>

    <div class="card">
      <h3>{{ t('mgmt.journal') }}</h3>
      <div class="row">
        <select v-model="logUnit">
          <option value="altrouter">
            {{ t('mgmt.unitPanel') }}
          </option>
          <option value="networkd">
            networkd
          </option>
          <option value="dnsmasq">
            dnsmasq
          </option>
          <option value="kernel">
            {{ t('mgmt.unitKernel') }}
          </option>
        </select>
        <input
          v-model.number="logLines"
          type="number"
          min="1"
          max="1000"
          class="lines"
        >
        <button
          class="btn"
          :disabled="logBusy"
          @click="loadLog"
        >
          {{ t('common.show') }}
        </button>
      </div>
      <p
        v-if="logErr"
        class="form-error"
      >
        {{ logErr }}
      </p>
      <pre
        v-if="logOut"
        class="out"
      >{{ logOut }}</pre>
    </div>

    <div class="card">
      <h3>{{ t('mgmt.access') }}</h3>
      <div class="row">
        <span>
          {{ t('mgmt.sshServer') }}
          <b>{{ ssh.enabled ? t('common.on') : t('common.off') }}</b>
          <span
            v-if="ssh.enabled && !ssh.active"
            class="warn-text"
          > {{ t('mgmt.notRunning') }}</span>
          · {{ t('mgmt.pwAuth') }}:
          <b>{{ ssh.password_auth ? t('common.on') : t('common.off') }}</b>
        </span>
        <button
          v-if="isAdmin"
          class="btn small"
          @click="toggleSsh"
        >
          {{ ssh.enabled ? t('common.disable') : t('common.enable') }}
        </button>
      </div>
      <div
        v-if="isAdmin"
        class="row"
      >
        <span>{{ t('mgmt.sshPort') }}</span>
        <input
          v-model.number="sshCfg.port"
          type="number"
          min="1"
          max="65535"
          class="port"
        >
        <select v-model="sshCfg.allow">
          <option value="">
            {{ t('mgmt.allNetworks') }}
          </option>
          <option
            v-for="s in segments"
            :key="s.id"
            :value="s.subnet"
          >
            {{ t('mgmt.onlyNet', { s: s.subnet, n: s.name }) }}
          </option>
        </select>
        <label class="check">
          <input
            v-model="sshCfg.pw"
            type="checkbox"
          >
          {{ t('mgmt.pwAuth') }}
        </label>
        <button
          class="btn small"
          :disabled="sshCfg.port < 1 || sshCfg.port > 65535"
          @click="applySshConfig"
        >
          {{ t('common.apply') }}
        </button>
      </div>
      <template v-if="isAdmin">
        <div class="row">
          <select
            v-model="sshKeyUser"
            @change="loadSshKeys"
          >
            <option
              v-for="u in sshUsers"
              :key="u.username"
              :value="u.username"
            >
              {{ t('mgmt.sshKeys', { u: u.username }) }}
            </option>
          </select>
        </div>
        <div class="row">
          <textarea
            v-model="sshKeyNew"
            rows="2"
            :placeholder="t('mgmt.phKey')"
          />
          <label class="btn">
            {{ t('mgmt.fromFile') }}
            <input
              type="file"
              accept=".pub"
              hidden
              @change="pickKeyFile"
            >
          </label>
          <button
            class="btn small"
            :disabled="!sshKeyNew || !sshKeyUser"
            @click="addSshKey"
          >
            {{ t('mgmt.addKey') }}
          </button>
        </div>
        <table
          v-if="sshKeys.length"
          class="data"
        >
          <thead>
            <tr>
              <th>{{ t('mgmt.fingerprint') }}</th>
              <th>{{ t('common.comment') }}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="k in sshKeys"
              :key="k.index"
            >
              <td class="mono">
                {{ k.fingerprint }}
              </td>
              <td>{{ k.comment }}</td>
              <td>
                <button
                  class="btn small"
                  @click="delSshKey(k)"
                >
                  {{ t('common.delete') }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
      <div
        v-if="isAdmin && mgmtIface"
        class="row"
      >
        <label class="check">
          <input
            v-model="mgmtOnly"
            type="checkbox"
          >
          {{ t('mgmt.mgmtOnly', { i: mgmtIface }) }}
        </label>
        <button
          class="btn small"
          @click="saveAccess"
        >
          {{ t('common.save') }}
        </button>
      </div>
      <p
        v-else-if="mgmtIface"
        class="muted"
      >
        {{ t('mgmt.restrict', { v: mgmtOnly ? t('mgmt.onlyIface', { i: mgmtIface }) : t('mgmt.allIfaces') }) }}
      </p>
      <div>
        <template v-if="tls.error">
          <p class="muted">
            {{ t('mgmt.tlsError', { e: tls.error }) }}
          </p>
        </template>
        <template v-else>
          <p class="muted">
            {{ t('mgmt.tlsInfo', { d: tls.not_after, i: (tls.issuer || []).map((p) => Object.values(p)[0]).join(', ') }) }}
          </p>
        </template>
        <template v-if="isAdmin">
          <div class="row">
            <textarea
              v-model="tlsCert"
              rows="3"
              :placeholder="t('mgmt.phCert')"
            />
            <textarea
              v-model="tlsKey"
              rows="3"
              :placeholder="t('mgmt.phKeyPem')"
            />
            <button
              class="btn"
              :disabled="!tlsCert || !tlsKey"
              @click="applyTls"
            >
              {{ t('mgmt.installCert') }}
            </button>
          </div>
          <div class="row">
            <textarea
              v-model="tlsHosts"
              rows="2"
              :placeholder="t('mgmt.phGenHosts')"
            />
            <button
              class="btn"
              :disabled="!tlsHosts.trim()"
              @click="generateTls"
            >
              {{ t('mgmt.genCert') }}
            </button>
          </div>
          <p
            v-if="tlsMsg"
            class="muted"
          >
            {{ tlsMsg }}
          </p>
        </template>
      </div>
      <p
        v-if="accessErr"
        class="form-error"
      >
        {{ accessErr }}
      </p>
    </div>

    <div
      v-if="isAdmin"
      class="card"
    >
      <h3>{{ t('mgmt.updates') }}</h3>
      <div class="row">
        <button
          class="btn"
          :disabled="updBusy"
          @click="checkUpdates"
        >
          {{ t('mgmt.checkUpdates') }}
        </button>
        <button
          v-if="updates !== null"
          class="btn primary"
          :disabled="updBusy"
          @click="applyUpdates"
        >
          {{ t('mgmt.applyUpdates', { n: updates }) }}
        </button>
      </div>
      <p
        v-if="updErr"
        class="form-error"
      >
        {{ updErr }}
      </p>
      <pre
        v-if="updOut"
        class="out"
      >{{ updOut }}</pre>
    </div>

    <div
      v-if="isAdmin"
      class="card"
    >
      <h3>{{ t('mgmt.power') }}</h3>
      <div class="row">
        <button
          class="btn"
          @click="powerAction('reboot')"
        >
          {{ t('mgmt.reboot') }}
        </button>
        <button
          class="btn"
          @click="powerAction('poweroff')"
        >
          {{ t('mgmt.poweroff') }}
        </button>
      </div>
      <p
        v-if="powerErr"
        class="form-error"
      >
        {{ powerErr }}
      </p>
    </div>

    <div
      v-if="isAdmin"
      class="card"
    >
      <h3
        class="collapsible"
        @click="journalOpen = !journalOpen"
      >
        {{ t('mgmt.changeLog') }}
        <button
          class="btn small"
          @click.stop="journalOpen = !journalOpen"
        >
          {{ journalOpen ? t('common.collapse') : t('common.expand') }}
        </button>
      </h3>
      <template v-if="journalOpen">
        <p
          v-if="journalErr"
          class="form-error"
        >
          {{ journalErr }}
        </p>
        <table
          v-else-if="journal.length"
          class="data"
        >
          <thead>
            <tr>
              <th>{{ t('mgmt.time') }}</th>
              <th>{{ t('mgmt.user') }}</th>
              <th>{{ t('mgmt.action') }}</th>
              <th>{{ t('mgmt.tx') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(e, i) in journal"
              :key="i"
            >
              <td>{{ fmtTime(e.ts) }}</td>
              <td>{{ e.username }}</td>
              <td>{{ e.action }}</td>
              <td>{{ e.id }}</td>
            </tr>
          </tbody>
        </table>
        <p
          v-else
          class="muted"
        >
          {{ t('mgmt.logEmpty') }}
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.management {
  display: grid;
  gap: 16px;
}
h3.collapsible {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.row input,
.row select {
  min-width: 140px;
}
.row .iface {
  min-width: 110px;
  max-width: 140px;
}
.row .filter {
  flex: 1;
  min-width: 180px;
}
.row .lines {
  min-width: 70px;
  max-width: 90px;
}
.row .port {
  min-width: 90px;
  max-width: 110px;
}
.mono {
  font-family: monospace;
}
.row textarea {
  flex: 1;
  min-width: 220px;
  font-family: monospace;
  font-size: 12px;
  resize: vertical;
}
label.btn {
  cursor: pointer;
}
label.btn.disabled {
  opacity: 0.6;
  pointer-events: none;
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
}
.out {
  margin-top: 8px;
  max-height: 300px;
  overflow: auto;
  background: #0f172a;
  color: #d1e3ff;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
