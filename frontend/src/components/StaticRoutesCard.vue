<script setup>
import { reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { routeFromForm, routeToForm } from '../utils/segments'
import { t } from '../i18n'

const props = defineProps({
  routes: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['applied'])

const rows = reactive([])
const error = ref('')
const saving = ref(false)

function rebuild() {
  rows.splice(0, rows.length, ...props.routes.map((route) => routeToForm(route)))
}

watch(
  () => props.routes,
  rebuild,
  { immediate: true, deep: true },
)

function addRow() {
  rows.push(routeToForm())
}

function removeRow(index) {
  rows.splice(index, 1)
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    const resp = await api.put('/network/routes', { routes: rows.map(routeFromForm) })
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
      <h3>{{ t('routes.title') }}</h3>
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
          <th>{{ t('routes.dest') }}</th>
          <th>{{ t('routes.gateway') }}</th>
          <th>{{ t('routes.metric') }}</th>
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
              v-model="row.dest"
              placeholder="10.5.0.0/16"
            >
          </td>
          <td>
            <input
              v-model="row.gateway"
              placeholder="192.168.10.1"
            >
          </td>
          <td>
            <input
              v-model="row.metric"
              class="num-input"
              inputmode="numeric"
              placeholder="—"
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
            {{ t('routes.none') }}
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint-text table-hint">
      {{ t('routes.hint') }}
    </p>
  </div>
</template>
