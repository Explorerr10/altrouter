import { describe, expect, it } from 'vitest'
import {
  policyFromForm,
  policyToForm,
  routeFromForm,
  routeToForm,
  segFromForm,
  segToForm,
  slugifyId,
} from '../src/utils/segments'

describe('slugifyId', () => {
  it('makes a latin slug and cuts to 9 chars', () => {
    expect(slugifyId('Home Net')).toBe('home-net')
    expect(slugifyId('Очень длинное название')).toBe('')
    expect(slugifyId('guest--2')).toBe('guest-2')
    expect(slugifyId('segment-identifier-long')).toBe('segment-i')
  })
})

describe('segment form', () => {
  const seg = {
    id: 'home',
    name: 'Домашняя',
    interfaces: ['enp5s0', 'enp6s0'],
    address: '192.168.10.1/24',
    dhcp: {
      enabled: true,
      pool_start: '192.168.10.50',
      pool_end: '192.168.10.150',
      lease_hours: 24,
      dns: ['1.1.1.1'],
    },
    reservations: [
      { mac: 'aa:bb:cc:dd:ee:ff', ip: '192.168.10.7', hostname: 'nas', comment: null },
    ],
  }

  it('round-trips a full segment', () => {
    expect(segFromForm(segToForm(seg))).toEqual(seg)
  })

  it('normalizes mac and drops empty reservations', () => {
    const form = segToForm(seg)
    form.reservations.push({ mac: '  ', ip: '10.0.0.1', hostname: '', comment: '' })
    form.reservations.push({ mac: '11:22:33:44:55:66', ip: ' 192.168.10.9 ', hostname: '', comment: 'точка' })
    const result = segFromForm(form)
    expect(result.reservations).toEqual([
      { mac: 'aa:bb:cc:dd:ee:ff', ip: '192.168.10.7', hostname: 'nas', comment: null },
      { mac: '11:22:33:44:55:66', ip: '192.168.10.9', hostname: null, comment: 'точка' },
    ])
  })

  it('drops dhcp fields when disabled', () => {
    const form = segToForm(seg)
    form.dhcpEnabled = false
    form.poolStart = '192.168.10.50'
    const result = segFromForm(form)
    expect(result.dhcp).toEqual({ enabled: false, pool_start: null, pool_end: null, lease_hours: 24, dns: [] })
  })

  it('defaults for a new segment', () => {
    expect(segToForm(null)).toMatchObject({
      id: '', name: '', ports: [], address: '', dhcpEnabled: false, leaseHours: 12,
    })
  })
})

describe('wan policy form', () => {
  it('round-trips with ping check', () => {
    const policy = {
      priority: 2,
      weight: 1,
      ping_check: { enabled: true, target: '8.8.8.8', interval_s: 15, fail_threshold: 5 },
    }
    expect(policyFromForm(policyToForm(policy))).toEqual(policy)
  })

  it('empty priority becomes null, defaults fill ping check', () => {
    const result = policyFromForm({
      priority: '',
      weight: '',
      pingEnabled: false,
      target: '',
      intervalS: '',
      failThreshold: '',
    })
    expect(result).toEqual({
      priority: null,
      weight: 1,
      ping_check: { enabled: false, target: '1.1.1.1', interval_s: 30, fail_threshold: 3 },
    })
  })

  it('toForm defaults for missing policy', () => {
    expect(policyToForm(undefined)).toMatchObject({ priority: '', pingEnabled: false, target: '1.1.1.1' })
  })
})

describe('route form', () => {
  it('round-trips and normalizes metric', () => {
    const route = { dest: '10.5.0.0/16', gateway: '192.168.1.1', metric: 50 }
    expect(routeFromForm(routeToForm(route))).toEqual(route)
    expect(routeFromForm(routeToForm({ dest: '10.0.0.0/8', gateway: '192.168.1.1' }))).toEqual({
      dest: '10.0.0.0/8',
      gateway: '192.168.1.1',
      metric: null,
    })
  })
})
