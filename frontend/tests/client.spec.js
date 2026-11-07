import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../src/i18n', () => {
  const known = new Set(['auth_required', 'diag_failed', 'invalid_credentials'])
  return {
    t: (key, vars) => {
      if (vars && 'n' in vars) return `${key}:${vars.n}`
      if (key.startsWith('err.')) {
        const name = key.slice(4)
        return known.has(name) ? name : key
      }
      return key
    },
  }
})

const { api } = await import('../src/api/client')

function resp(status, body) {
  return { ok: status < 400, status, text: async () => JSON.stringify(body) }
}

async function expectError(promise, message, status) {
  await expect(promise).rejects.toMatchObject({ message, status })
}

describe('api client auth redirect', () => {
  let assign

  beforeEach(() => {
    assign = vi.fn()
    vi.stubGlobal('window', { location: { pathname: '/management', search: '?x=1', assign } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  it('returns parsed body on success', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => resp(200, { ok: true })))
    await expect(api.get('/auth/me')).resolves.toEqual({ ok: true })
    expect(assign).not.toHaveBeenCalled()
  })

  it('redirects to login with current path on expired session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => resp(401, { detail: 'Требуется вход в систему', code: 'auth_required' })),
    )
    await expectError(api.get('/network/interfaces/status'), 'auth_required', 401)
    expect(assign).toHaveBeenCalledWith('/login?redirect=%2Fmanagement%3Fx%3D1')
  })

  it('does not redirect on login form failure', async () => {
    vi.stubGlobal('window', { location: { pathname: '/login', search: '', assign } })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => resp(401, { detail: 'б', code: 'invalid_credentials' })),
    )
    await expectError(api.post('/auth/login', {}), 'invalid_credentials', 401)
    expect(assign).not.toHaveBeenCalled()
  })

  it('keeps raw detail for dynamic error families', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => resp(400, { detail: 'б', code: 'diag_failed' })))
    await expectError(api.post('/system/diag/ping', {}), 'diag_failed: б', 400)
    expect(assign).not.toHaveBeenCalled()
  })

  it('falls back to http error when code is unknown', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => resp(503, null)))
    await expectError(api.get('/system/info'), 'common.httpError:503', 503)
  })
})
