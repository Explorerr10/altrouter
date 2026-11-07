import { redirectToLogin } from './client'

export function createStatsSocket(onSample, onStatus) {
  let ws = null
  let closed = false
  let timer = null

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/ws/stats`)
    ws.onopen = () => onStatus(true)
    ws.onmessage = (event) => {
      try {
        onSample(JSON.parse(event.data))
      } catch {
        onSample(null)
      }
    }
    ws.onclose = (event) => {
      onStatus(false)
      if (event.code === 4401) {
        redirectToLogin()
        return
      }
      if (!closed) {
        timer = setTimeout(connect, 2000)
      }
    }
    ws.onerror = () => ws.close()
  }

  connect()

  return {
    stop() {
      closed = true
      clearTimeout(timer)
      if (ws) {
        ws.close()
      }
    },
  }
}
