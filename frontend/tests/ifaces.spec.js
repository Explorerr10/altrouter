import { describe, expect, it } from 'vitest'
import { defaultItem, fromForm, secondsLeft, toForm } from '../src/utils/ifaces'
import { t } from '../src/i18n'

describe('fromForm', () => {
  it('builds off item without any parameters', () => {
    const item = fromForm({
      name: 'enp5s0',
      role: 'off',
      ipv4: 'dhcp',
      address: 'x',
      gateway: 'y',
      dnsText: '1.1.1.1',
      mtu: '9000',
    })
    expect(item).toEqual({
      name: 'enp5s0',
      role: 'off',
      ipv4: null,
      address: null,
      gateway: null,
      dns: [],
      mtu: null,
      vlan_id: null,
      mac: null,
      pppoe_username: null,
      pppoe_password: null,
    })
  })

  it('parses dns list and mtu for wan dhcp', () => {
    const item = fromForm({
      name: 'enp5s0',
      role: 'wan',
      ipv4: 'dhcp',
      address: '',
      gateway: '',
      dnsText: '1.1.1.1, 8.8.8.8',
      mtu: '1500',
    })
    expect(item).toEqual({
      name: 'enp5s0',
      role: 'wan',
      ipv4: 'dhcp',
      address: null,
      gateway: null,
      dns: ['1.1.1.1', '8.8.8.8'],
      mtu: 1500,
      vlan_id: null,
      mac: null,
      pppoe_username: null,
      pppoe_password: null,
    })
  })

  it('keeps address and gateway for wan static', () => {
    const item = fromForm({
      name: 'enp6s0',
      role: 'wan',
      ipv4: 'static',
      address: ' 192.168.1.2/24 ',
      gateway: '192.168.1.1',
      dnsText: '',
      mtu: '',
      mac: ' AA:BB:CC:DD:EE:FF ',
    })
    expect(item.address).toBe('192.168.1.2/24')
    expect(item.gateway).toBe('192.168.1.1')
    expect(item.mtu).toBeNull()
    expect(item.mac).toBe('aa:bb:cc:dd:ee:ff')
  })

  it('collects pppoe credentials and clears them otherwise', () => {
    const item = fromForm({
      name: 'enp5s0',
      role: 'wan',
      ipv4: 'pppoe',
      dnsText: '1.1.1.1',
      mtu: '1492',
      pppoe_username: ' user@isp ',
      pppoe_password: ' pa55 ',
    })
    expect(item.pppoe_username).toBe('user@isp')
    expect(item.pppoe_password).toBe('pa55')
    expect(item.address).toBeNull()
    expect(item.gateway).toBeNull()
    const dhcp = fromForm({ name: 'enp6s0', role: 'wan', ipv4: 'dhcp', pppoe_username: 'x' })
    expect(dhcp.pppoe_username).toBeNull()
    expect(dhcp.pppoe_password).toBeNull()
  })

  it('forces static and drops gateway/dns for lan', () => {
    const item = fromForm({
      name: 'enp7s0',
      role: 'lan',
      ipv4: 'dhcp',
      address: '192.168.10.1/24',
      gateway: '192.168.10.1',
      dnsText: '1.1.1.1',
      mtu: '',
      mac: 'aa:bb:cc:dd:ee:ff',
    })
    expect(item).toEqual({
      name: 'enp7s0',
      role: 'lan',
      ipv4: 'static',
      address: '192.168.10.1/24',
      gateway: null,
      dns: [],
      mtu: null,
      vlan_id: null,
      mac: null,
      pppoe_username: null,
      pppoe_password: null,
    })
  })
})

describe('toForm', () => {
  it('round-trips a static wan item', () => {
    const source = {
      name: 'enp6s0',
      role: 'wan',
      ipv4: 'static',
      address: '192.168.1.2/24',
      gateway: '192.168.1.1',
      dns: ['1.1.1.1', '8.8.8.8'],
      mtu: 1500,
      vlan_id: null,
      mac: 'aa:bb:cc:dd:ee:ff',
      pppoe_username: null,
      pppoe_password: null,
    }
    expect(fromForm(toForm(source))).toEqual(source)
  })

  it('defaults for an unconfigured interface', () => {
    expect(toForm(null)).toMatchObject({ name: '', role: 'off', ipv4: 'dhcp', dnsText: '' })
  })
})

describe('secondsLeft', () => {
  it('rounds and clamps to zero', () => {
    const now = Date.now() / 1000
    expect(secondsLeft(now + 10.4, now)).toBe(10)
    expect(secondsLeft(now - 5, now)).toBe(0)
  })

  it('handles invalid deadline', () => {
    expect(secondsLeft(undefined)).toBe(0)
    expect(secondsLeft(Number.NaN)).toBe(0)
  })
})

describe('defaultItem', () => {
  it('creates off item with role labels available', () => {
    expect(defaultItem('enp8s0')).toMatchObject({ name: 'enp8s0', role: 'off' })
    expect(t('role.off')).toBe('Выключен')
  })
})
