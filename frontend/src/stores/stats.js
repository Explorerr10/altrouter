import { defineStore } from 'pinia'

const MAX_POINTS = 300

export const useStatsStore = defineStore('stats', {
  state: () => ({
    connected: false,
    last: null,
    ts: [],
    cpu: [],
    ram: [],
    ifaceRates: {},
  }),
  actions: {
    push(sample) {
      if (!sample) {
        return
      }
      this.last = sample
      this.ts.push(sample.ts)
      this.cpu.push(sample.cpu_percent)
      this.ram.push(sample.ram_percent)
      if (this.ts.length > MAX_POINTS) {
        this.ts.shift()
        this.cpu.shift()
        this.ram.shift()
      }
      this.ifaceRates = sample.interfaces || {}
    },
    setConnected(value) {
      this.connected = value
    },
  },
})
