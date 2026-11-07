<script setup>
import { reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import PortForwardDialog from './PortForwardDialog.vue'
import { forwardFromForm, forwardToForm } from '../utils/rules'
import { t } from '../i18n'

const props = defineProps({
  forwards: { type: Array, default: () => [] },
  wanIfaces: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['applied'])

const rows = reactive([])
const error = ref('')
const saving = ref(false)
const dialog = ref(null)
const dialogError = ref('')

function rebuild() {
  rows.splice(0, rows.length, ...props.forwards.map((fw) => forwardToForm(fw)))
}

watch(
  () => props.forwards,
  rebuild,
  { immediate: true, deep: true },
)

function wanLabel(value) {
  return value || t('pf.allWan')
}

function openCreate() {
  dialogError.value = ''
  dialog.value = { index: -1, initial: null }
}

function openEdit(index) {
  dialogError.value = ''
  dialog.value = { index, initial: forwardFromForm(rows[index]) }
}

async function saveForward(fw) {
  dialogError.value = ''
  saving.value = true
  try {
    const next = [...rows.map(forwardFromForm)]
    if (dialog.value.index >= 0) {
      next[dialog.value.index] = fw
    } else {
      next.push(fw)
    }
    const resp = await api.put('/network/forwards', { forwards: next })
    emit('applied', resp.pending)
    dialog.value = null
  } catch (err) {
    dialogError.value = err.message || t('common.applyError')
  } finally {
    saving.value = false
  }
}

function removeRow(index) {
  rows.splice(index, 1)
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    const resp = await api.put('/network/forwards', { forwards: rows.map(forwardFromForm) })
    emit('applied', resp.pending)
  } catch (err) {
    error.value = err.message || t('common.applyError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="card table-card">
    <div class="card-head">
      <h3>{{ t('pf.title') }}</h3>
      <div class="dialog-actions">
        <button
          class="btn small"
          :disabled="!props.wanIfaces.length"
          :title="!props.wanIfaces.length ? t('pf.needWan') : ''"
          @click="openCreate"
        >
          {{ t('pf.add') }}
        </button>
        <button
          class="btn small primary"
          :disabled="saving || props.busy"
          @click="save"
        >
          {{ t('common.apply') }}
        </button>
      </div>
    </div>
    <p
      v-if="error"
      class="form-error table-error"
    >
      {{ error }}
    </p>
    <table class="data">
      <thead>
        <tr>
          <th>WAN</th>
          <th>{{ t('common.proto') }}</th>
          <th>{{ t('pf.extPortCol') }}</th>
          <th>{{ t('pf.toAddr') }}</th>
          <th>{{ t('pf.toPortCol') }}</th>
          <th>{{ t('common.comment') }}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="index"
        >
          <td>{{ wanLabel(row.wan) }}</td>
          <td>{{ t('fw.proto.' + row.proto) }}</td>
          <td><span class="mono">{{ row.port }}</span></td>
          <td><span class="mono">{{ row.toIp }}</span></td>
          <td><span class="mono">{{ row.toPort || row.port }}</span></td>
          <td>{{ row.comment }}</td>
          <td>
            <button
              class="btn small"
              @click="openEdit(index)"
            >
              {{ t('common.edit') }}
            </button>
            <button
              class="btn small"
              @click="removeRow(index)"
            >
              {{ t('common.delete') }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="7">
            {{ t('pf.none') }}
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint-text table-hint">
      {{ t('pf.hint') }}
    </p>

    <PortForwardDialog
      v-if="dialog"
      :initial="dialog.initial"
      :wan-ifaces="props.wanIfaces"
      :error="dialogError"
      :busy="saving"
      @close="dialog = null"
      @save="saveForward"
    />
  </div>
</template>
