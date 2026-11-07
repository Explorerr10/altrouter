<script setup>
import { reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import FirewallRuleDialog from './FirewallRuleDialog.vue'
import { ruleDestination, ruleFromForm, ruleSource, ruleToForm } from '../utils/rules'
import { t } from '../i18n'

const props = defineProps({
  rules: { type: Array, default: () => [] },
  zones: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['applied'])

const rows = reactive([])
const error = ref('')
const saving = ref(false)
const dialog = ref(null)
const dialogError = ref('')
const dragIndex = ref(-1)

function rebuild() {
  rows.splice(0, rows.length, ...props.rules.map((rule) => ruleToForm(rule)))
}

watch(
  () => props.rules,
  rebuild,
  { immediate: true, deep: true },
)

function zoneLabel(value) {
  const zone = props.zones.find((item) => item.value === value)
  return zone ? zone.label : value
}

function moveRow(from, to) {
  if (to < 0 || to >= rows.length || from === to) {
    return
  }
  const [moved] = rows.splice(from, 1)
  rows.splice(to, 0, moved)
}

function onDragStart(index) {
  dragIndex.value = index
}

function onDrop(index) {
  moveRow(dragIndex.value, index)
  dragIndex.value = -1
}

function openCreate() {
  dialogError.value = ''
  dialog.value = { initial: null }
}

function openEdit(index) {
  dialogError.value = ''
  dialog.value = { index, initial: ruleFromForm(rows[index]) }
}

async function saveRule(rule) {
  dialogError.value = ''
  saving.value = true
  try {
    const next = [...rows.map(ruleFromForm)]
    if (dialog.value.index >= 0) {
      next[dialog.value.index] = rule
    } else {
      next.push(rule)
    }
    await putRules(next)
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

async function putRules(rules) {
  error.value = ''
  const resp = await api.put('/network/firewall', { rules })
  emit('applied', resp.pending)
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    await putRules(rows.map(ruleFromForm))
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
      <h3>{{ t('fw.title') }}</h3>
      <div class="dialog-actions">
        <button
          class="btn small"
          @click="openCreate"
        >
          {{ t('fw.add') }}
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
          <th class="num-col">
            №
          </th>
          <th>{{ t('fw.direction') }}</th>
          <th>{{ t('fw.zone') }}</th>
          <th>{{ t('common.proto') }}</th>
          <th>{{ t('fw.src') }}</th>
          <th>{{ t('fw.dst') }}</th>
          <th>{{ t('fw.action') }}</th>
          <th>{{ t('common.comment') }}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="index"
          :draggable="true"
          @dragstart="onDragStart(index)"
          @dragover.prevent
          @drop.prevent="onDrop(index)"
        >
          <td class="num-col">
            {{ index + 1 }}
          </td>
          <td>{{ t('fw.dir.' + row.direction) }}</td>
          <td>{{ zoneLabel(row.zone) }}</td>
          <td>{{ t('fw.proto.' + row.proto) }}</td>
          <td><span class="mono">{{ ruleSource(row) }}</span></td>
          <td><span class="mono">{{ ruleDestination(row) }}</span></td>
          <td>
            <span :class="row.action === 'allow' ? 'ok-text' : 'warn-text'">
              {{ t('fw.action.' + row.action) }}
            </span>
          </td>
          <td>{{ row.comment }}</td>
          <td>
            <button
              class="btn small"
              :disabled="index === 0"
              :title="t('fw.up')"
              @click="moveRow(index, index - 1)"
            >
              ↑
            </button>
            <button
              class="btn small"
              :disabled="index === rows.length - 1"
              :title="t('fw.down')"
              @click="moveRow(index, index + 1)"
            >
              ↓
            </button>
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
          <td colspan="9">
            {{ t('fw.none') }}
          </td>
        </tr>
      </tbody>
    </table>
    <p class="hint-text table-hint">
      {{ t('fw.hint') }}
    </p>

    <FirewallRuleDialog
      v-if="dialog"
      :initial="dialog.initial"
      :zones="props.zones"
      :error="dialogError"
      :busy="saving"
      @close="dialog = null"
      @save="saveRule"
    />
  </div>
</template>
