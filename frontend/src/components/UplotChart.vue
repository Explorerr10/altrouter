<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { t } from '../i18n'

const props = defineProps({
  data: { type: Array, required: true },
  label: { type: String, default: '' },
  color: { type: String, default: '#2563eb' },
  fillColor: { type: String, default: 'rgba(37, 99, 235, 0.1)' },
  max: { type: Number, default: 100 },
  height: { type: Number, default: 150 },
})

const el = ref(null)
let chart = null
let observer = null

const fmtTime = uPlot.fmtDate('{H}:{mm}:{ss}')

function buildOptions(width) {
  return {
    width,
    height: props.height,
    scales: {
      y: { range: [0, props.max] },
    },
    series: [
      {
        label: t('chart.time'),
        value: (u, v) => (v == null ? '--' : fmtTime(new Date(v * 1000))),
      },
      {
        label: props.label,
        stroke: props.color,
        width: 2,
        fill: props.fillColor,
        points: { show: false },
      },
    ],
    axes: [
      {
        values: (u, vals) => vals.map((v) => (v == null ? '' : fmtTime(new Date(v * 1000)))),
        font: '11px system-ui, sans-serif',
        stroke: '#9ca3af',
        grid: { show: false },
      },
      {
        values: (u, vals) => vals.map((v) => `${Math.round(v)}%`),
        font: '11px system-ui, sans-serif',
        stroke: '#9ca3af',
        grid: { stroke: '#eef0f3', width: 1 },
      },
    ],
    legend: { show: false },
    cursor: { drag: { x: false, y: false } },
  }
}

onMounted(() => {
  chart = new uPlot(buildOptions(el.value.clientWidth), props.data, el.value)
  observer = new ResizeObserver((entries) => {
    const width = entries[0].contentRect.width
    if (chart && width > 0) {
      chart.setSize({ width, height: props.height })
    }
  })
  observer.observe(el.value)
})

watch(
  () => props.data,
  (d) => {
    if (chart) {
      chart.setData(d)
    }
  },
  { deep: true },
)

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
  }
  if (chart) {
    chart.destroy()
  }
})
</script>

<template>
  <div
    ref="el"
    class="uplot-holder"
  />
</template>
