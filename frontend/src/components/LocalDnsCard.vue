<script setup>
import { reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { recordFromForm, recordToForm } from '../utils/rules'
import { t } from '../i18n'

const props = defineProps({
  records: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['applied'])

const rows = reactive([])
const error = ref('')
const saving = ref(false)

function rebuild() {
  rows.splice(0, rows.length, ...props.records.map((rec) => recordToForm(rec)))
}

watch(
  () => props.records,
  rebuild,
  { immediate: true, deep: true },
)

function addRow() {
  rows.push(recordToForm())
}

function removeRow(index) {
  rows.splice(index, 1)
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    const resp = await api.put('/network/dns', { records: rows.map(recordFromForm) })
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
      <h3>{{ t('dns.title') }}</h3>
      <div class="dialog-actions">
        <button
          class="btn small"
          @click="addRow"
        >
          {{ t('common.add') }}
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
          <th>{{ t('col.name') }}</th>
          <th>{{ t('col.ip') }}</th>
          <th>{{ t('common.comment') }}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="index"
        >
          <td>
            <input
              v-model="row.hostname"
              placeholder="nas"
            >
          </td>
          <td>
            <input
              v-model="row.ip"
              placeholder="192.168.10.20"
            >
          </td>
          <td>
            <input
              v-model="row.comment"
              :placeholder="t('dns.phComment')"
            >
          </td>
          <td>
            <button
              class="btn small"
              @click="removeRow(index)"
            >
              {{ t('common.delete') }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="4">
            {{ t('dns.none') }}
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint-text table-hint">
      {{ t('dns.hint') }}
    </p>
  </div>
</template>
