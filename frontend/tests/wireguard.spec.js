import { describe, expect, it } from 'vitest'
import {
  bytesText,
  handshakeText,
  ifaceFromForm,
  ifaceToForm,
  peerFromForm,
  peerToForm,
  tunnelStatus,
} from '../src/utils/wireguard'

describe('wireguard iface form', () => {
  const iface = {
    id: 'home',
    name: 'Дом',
    enabled: true,
    address: '10.9.0.1/24',
    listen_port: '51820',
    private_key: null,
    public_key: 'PUB=',
    route_mode: 'devices',
    priority: 1,
    devices: ['192.168.10.55/32'],
    endpoint: 'vpn.example.com',
    mtu: null,
    peers: [
      {
        name: 'phone',
        public_key: 'PK=',
        private_key: null,
        allowed_ips: ['10.9.0.2/32'],
        preshared_key: null,
        endpoint: null,
        keepalive: 25,
        comment: 'iPhone',
      },
    ],
  }

  it('round-trips a full tunnel', () => {
    const form = ifaceToForm(iface)
    expect(form.peers).toHaveLength(1)
    expect(ifaceFromForm(form)).toEqual(iface)
  })

  it('round-trips a peer', () => {
    expect(peerFromForm(peerToForm(iface.peers[0]))).toEqual(iface.peers[0])
  })

  it('clears routing fields in none mode', () => {
    const form = ifaceToForm(iface)
    form.routeMode = 'none'
    const back = ifaceFromForm(form)
    expect(back.devices).toEqual([])
    expect(back.priority).toBeNull()
  })

  it('splits devices and allowed ips lists', () => {
    const form = ifaceToForm(null)
    form.id = 'w'
    form.name = 'W'
    form.address = '10.1.0.1/24'
    form.listenPort = '51821'
    form.routeMode = 'devices'
    form.devices = '192.168.1.5, 192.168.1.6/32'
    form.peers = [
      {
        name: 'p',
        publicKey: '',
        privateKey: 'KEY=',
        allowedIps: '10.1.0.2/32 10.1.0.3',
        presharedKey: '',
        endpoint: '',
        keepalive: '',
        comment: '',
      },
    ]
    const back = ifaceFromForm(form)
    expect(back.devices).toEqual(['192.168.1.5', '192.168.1.6/32'])
    expect(back.peers[0].allowed_ips).toEqual(['10.1.0.2/32', '10.1.0.3'])
    expect(back.peers[0].private_key).toBe('KEY=')
  })
})

describe('status helpers', () => {
  const status = {
    'arwg-home': {
      peers: {
        'PK=': { handshake: Math.floor(Date.now() / 1000) - 30, rx: 2048, tx: 1024 },
        'X=': { handshake: 0, rx: 0, tx: 0 },
      },
    },
  }

  it('matches peers by public key', () => {
    const peers = tunnelStatus(status, { id: 'home' })
    expect(peers).toHaveLength(2)
    expect(tunnelStatus(status, { id: 'other' })).toEqual([])
  })

  it('formats handshake age', () => {
    expect(handshakeText(Math.floor(Date.now() / 1000) - 30)).toBe('активен')
    expect(handshakeText(0)).toBe('нет рукопожатия')
    expect(handshakeText(Math.floor(Date.now() / 1000) - 300)).toBe('5 мин назад')
  })

  it('formats bytes', () => {
    expect(bytesText(0)).toBe('—')
    expect(bytesText(2048)).toBe('2.0 КиБ')
    expect(bytesText(512)).toBe('512 Б')
  })
})
