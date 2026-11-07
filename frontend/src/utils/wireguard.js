import { t } from '../i18n'

function optional(value) {
  if (value === null || value === undefined) {
    return null
  }
  if (typeof value === 'number') {
    return value
  }
  const text = String(value).trim()
  return text || null
}

function splitList(value) {
  return String(value ?? '')
    .split(/[\s,]+/)
    .filter(Boolean)
}

export function ifaceToForm(wg) {
  return {
    id: wg?.id ?? '',
    name: wg?.name ?? '',
    enabled: wg?.enabled ?? true,
    address: wg?.address ?? '',
    listenPort: wg?.listen_port ?? '',
    privateKey: wg?.private_key ?? '',
    publicKey: wg?.public_key ?? '',
    routeMode: wg?.route_mode ?? 'none',
    priority: wg?.priority ?? 1,
    devices: (wg?.devices ?? []).join(', '),
    endpoint: wg?.endpoint ?? '',
    mtu: wg?.mtu ?? '',
    peers: (wg?.peers ?? []).map(peerToForm),
  }
}

export function ifaceFromForm(form) {
  return {
    id: form.id.trim(),
    name: form.name.trim(),
    enabled: form.enabled,
    address: form.address.trim(),
    listen_port: String(form.listenPort ?? '').trim(),
    private_key: optional(form.privateKey),
    public_key: optional(form.publicKey),
    route_mode: form.routeMode,
    priority: form.routeMode === 'all' || form.routeMode === 'devices' ? form.priority : null,
    devices: form.routeMode === 'devices' ? splitList(form.devices) : [],
    endpoint: optional(form.endpoint),
    mtu: optional(form.mtu),
    peers: form.peers.map(peerFromForm),
  }
}

export function peerToForm(peer) {
  return {
    name: peer?.name ?? '',
    publicKey: peer?.public_key ?? '',
    privateKey: peer?.private_key ?? '',
    allowedIps: (peer?.allowed_ips ?? []).join(', '),
    presharedKey: peer?.preshared_key ?? '',
    endpoint: peer?.endpoint ?? '',
    keepalive: peer?.keepalive ?? '',
    comment: peer?.comment ?? '',
  }
}

export function peerFromForm(form) {
  return {
    name: form.name.trim(),
    public_key: optional(form.publicKey),
    private_key: optional(form.privateKey),
    allowed_ips: splitList(form.allowedIps),
    preshared_key: optional(form.presharedKey),
    endpoint: optional(form.endpoint),
    keepalive: optional(form.keepalive),
    comment: optional(form.comment),
  }
}

export function emptyPeerForm() {
  return {
    name: '',
    publicKey: '',
    privateKey: '',
    allowedIps: '',
    presharedKey: '',
    endpoint: '',
    keepalive: '',
    comment: '',
  }
}

export function handshakeText(handshake) {
  if (!handshake) {
    return t('wg.hsNone')
  }
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - handshake))
  if (seconds < 120) {
    return t('wg.hsActive')
  }
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) {
    return t('wg.hsMinAgo', { m: minutes })
  }
  return t('wg.hsHourAgo', { h: Math.floor(minutes / 60) })
}

export function bytesText(value) {
  const bytes = Number(value ?? 0)
  if (!bytes) {
    return '—'
  }
  const units = ['Б', 'КиБ', 'МиБ', 'ГиБ']
  let index = 0
  let size = bytes
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(size >= 10 || index === 0 ? 0 : 1)} ${units[index]}`
}

export function tunnelStatus(status, tunnel) {
  const info = status[tunnel.id ? `arwg-${tunnel.id}` : ''] ?? { peers: {} }
  return Object.keys(info.peers ?? {}).map((key) => ({ public_key: key, ...info.peers[key] }))
}
