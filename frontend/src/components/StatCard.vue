<script setup>
defineProps({
  title: { type: String, required: true },
  value: { type: String, default: '—' },
  note: { type: String, default: '' },
})
</script>

<template>
  <div class="card stat-card">
    <div class="stat-title">
      {{ title }}
    </div>
    <div class="stat-value">
      {{ value }}
    </div>
    <div
      v-if="note"
      class="stat-note"
    >
      {{ note }}
    </div>
  </div>
</template>
