import { t } from '../i18n'

function optional(value) {
  const text = String(value ?? '').trim()
  return text || null
}

export function ruleToForm(rule) {
  return {
    direction: rule?.direction ?? 'forward',
    zone: rule?.zone ?? 'wan',
    proto: rule?.proto ?? 'any',
    srcIp: rule?.src_ip ?? '',
    srcPort: rule?.src_port ?? '',
    dstIp: rule?.dst_ip ?? '',
    dstPort: rule?.dst_port ?? '',
    action: rule?.action ?? 'allow',
    comment: rule?.comment ?? '',
  }
}

export function ruleFromForm(form) {
  const withPorts = form.proto !== 'any'
  return {
    direction: form.direction,
    zone: form.zone,
    proto: form.proto,
    src_ip: optional(form.srcIp),
    src_port: withPorts ? optional(form.srcPort) : null,
    dst_ip: optional(form.dstIp),
    dst_port: withPorts ? optional(form.dstPort) : null,
    action: form.action,
    comment: optional(form.comment),
  }
}

export function forwardToForm(fw) {
  return {
    wan: fw?.wan ?? '',
    proto: fw?.proto ?? 'tcp',
    port: fw?.port ?? '',
    toIp: fw?.to_ip ?? '',
    toPort: fw?.to_port ?? '',
    comment: fw?.comment ?? '',
  }
}

export function forwardFromForm(form) {
  return {
    wan: optional(form.wan),
    proto: form.proto,
    port: String(form.port ?? '').trim(),
    to_ip: optional(form.toIp),
    to_port: optional(form.toPort),
    comment: optional(form.comment),
  }
}

export function recordToForm(rec) {
  return {
    hostname: rec?.hostname ?? '',
    ip: rec?.ip ?? '',
    comment: rec?.comment ?? '',
  }
}

export function recordFromForm(form) {
  return {
    hostname: String(form.hostname ?? '').trim(),
    ip: String(form.ip ?? '').trim(),
    comment: optional(form.comment),
  }
}

export function ruleSource(rule) {
  const ip = rule.src_ip ?? ''
  const port = rule.src_port ? `:${rule.src_port}` : ''
  return `${ip}${port}` || t('common.any')
}

export function ruleDestination(rule) {
  const ip = rule.dst_ip ?? ''
  const port = rule.dst_port ? `:${rule.dst_port}` : ''
  return `${ip}${port}` || t('common.any')
}
