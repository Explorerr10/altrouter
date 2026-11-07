import { t } from '../i18n'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

const DYNAMIC_CODES = new Set([
  'network_invalid', 'txn_conflict', 'apply_failed', 'rollback_failed', 'wg_keys_failed',
  'wg_render_failed', 'user_invalid', 'backup_invalid', 'diag_failed', 'logs_failed',
  'ssh_failed', 'tls_failed', 'updates_failed', 'power_failed', 'validation_error',
  'mgmt_protected', 'link_failed',
])

function rawDetail(body) {
  if (body && typeof body.detail === 'string') return body.detail
  if (body && Array.isArray(body.detail) && body.detail.length) {
    const first = body.detail[0]
    if (first && typeof first.msg === 'string') {
      return first.msg.replace(/^Value error,\s*/, '')
    }
  }
  return null
}

function extractDetail(body, status) {
  const raw = rawDetail(body)
  const code = body && typeof body.code === 'string' ? body.code : null
  if (code && t(`err.${code}`) !== `err.${code}`) {
    if (DYNAMIC_CODES.has(code) && raw) return `${t(`err.${code}`)}: ${raw}`
    return t(`err.${code}`)
  }
  return raw ?? t('common.httpError', { n: status })
}

export function redirectToLogin() {
  if (typeof window === 'undefined' || window.location.pathname === '/login') return
  const target = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.assign(`/login?redirect=${target}`)
}

async function request(path, options = {}) {
  const resp = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...options,
  })
  const raw = await resp.text()
  let body
  try {
    body = JSON.parse(raw)
  } catch {
    body = null
  }
  if (!resp.ok) {
    if (resp.status === 401 && body && body.code === 'auth_required') {
      redirectToLogin()
    }
    throw new ApiError(extractDetail(body, resp.status), resp.status)
  }
  return body ?? raw
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body ?? {}) }),
  put: (path, body) => request(path, { method: 'PUT', body: JSON.stringify(body ?? {}) }),
  del: (path) => request(path, { method: 'DELETE' }),
}
