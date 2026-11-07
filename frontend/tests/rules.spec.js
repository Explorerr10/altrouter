import { describe, expect, it } from 'vitest'
import {
  forwardFromForm,
  forwardToForm,
  recordFromForm,
  recordToForm,
  ruleDestination,
  ruleFromForm,
  ruleSource,
  ruleToForm,
} from '../src/utils/rules'

describe('firewall rule form', () => {
  const rule = {
    direction: 'input',
    zone: 'wan',
    proto: 'tcp',
    src_ip: '203.0.113.0/24',
    src_port: null,
    dst_ip: null,
    dst_port: '443',
    action: 'drop',
    comment: 'сеть-поставщика',
  }

  it('round-trips a full rule', () => {
    expect(ruleFromForm(ruleToForm(rule))).toEqual(rule)
  })

  it('fills defaults for a new rule', () => {
    expect(ruleToForm(null)).toEqual({
      direction: 'forward',
      zone: 'wan',
      proto: 'any',
      srcIp: '',
      srcPort: '',
      dstIp: '',
      dstPort: '',
      action: 'allow',
      comment: '',
    })
  })

  it('drops ports for proto any and trims optionals', () => {
    const form = ruleToForm({ proto: 'any', srcPort: ' 80 ', comment: '  ' })
    const result = ruleFromForm(form)
    expect(result.src_port).toBeNull()
    expect(result.comment).toBeNull()
    expect(result.dst_ip).toBeNull()
  })

  it('describes source and destination', () => {
    expect(ruleSource({ src_ip: '10.0.0.0/8', src_port: '1000-2000' })).toBe('10.0.0.0/8:1000-2000')
    expect(ruleDestination({ dst_ip: null, dst_port: null })).toBe('любой')
    expect(ruleDestination({ dst_ip: '192.168.1.5', dst_port: '80' })).toBe('192.168.1.5:80')
  })
})

describe('port forward form', () => {
  const fw = {
    wan: null,
    proto: 'tcp',
    port: '8080',
    to_ip: '192.168.10.50',
    to_port: '80',
    comment: null,
  }

  it('round-trips a forward with empty wan', () => {
    expect(forwardFromForm(forwardToForm(fw))).toEqual(fw)
  })

  it('maps wan name and trims fields', () => {
    const result = forwardFromForm(forwardToForm({ wan: 'enp5s0', port: ' 53 ', to_ip: ' 192.168.1.2 ' }))
    expect(result.wan).toBe('enp5s0')
    expect(result.port).toBe('53')
    expect(result.to_ip).toBe('192.168.1.2')
    expect(result.to_port).toBeNull()
    expect(result.comment).toBeNull()
  })
})

describe('dns record form', () => {
  const rec = { hostname: 'nas', ip: '192.168.10.20', comment: 'хранилище' }

  it('round-trips a record', () => {
    expect(recordFromForm(recordToForm(rec))).toEqual(rec)
  })

  it('trims name and ip, nulls comment', () => {
    const result = recordFromForm(recordToForm({ hostname: ' nas ', ip: ' 192.168.10.20 ', comment: '' }))
    expect(result.hostname).toBe('nas')
    expect(result.ip).toBe('192.168.10.20')
    expect(result.comment).toBeNull()
  })
})
