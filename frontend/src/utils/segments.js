export function slugifyId(name) {
  return String(name ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 9)
}

export function emptyReservation() {
  return { mac: '', ip: '', hostname: '', comment: '' }
}

export function ipInCidr(ip, cidr) {
  const [base, bitsRaw] = String(cidr ?? '').split('/')
  const bits = Number(bitsRaw)
  if (!base || !Number.isInteger(bits) || bits < 0 || bits > 32) {
    return false
  }
  const octets = (text) => String(text ?? '').trim().split('.').map(Number)
  const baseParts = octets(base)
  const ipParts = octets(ip)
  if (baseParts.length !== 4 || ipParts.length !== 4) {
    return false
  }
  if ([...baseParts, ...ipParts].some((n) => !Number.isInteger(n) || n < 0 || n > 255)) {
    return false
  }
  const toInt = (parts) => (((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0)
  const mask = bits === 0 ? 0 : (0xffffffff << (32 - bits)) >>> 0
  return (toInt(ipParts) & mask) === (toInt(baseParts) & mask)
}

export function segToForm(seg) {
  return {
    id: seg?.id ?? '',
    name: seg?.name ?? '',
    ports: [...(seg?.interfaces ?? [])],
    address: seg?.address ?? '',
    dhcpEnabled: seg?.dhcp?.enabled ?? false,
    poolStart: seg?.dhcp?.pool_start ?? '',
    poolEnd: seg?.dhcp?.pool_end ?? '',
    leaseHours: seg?.dhcp?.lease_hours ?? 12,
    dnsText: (seg?.dhcp?.dns ?? []).join(', '),
    reservations: (seg?.reservations ?? []).map((r) => ({
      mac: r.mac ?? '',
      ip: r.ip ?? '',
      hostname: r.hostname ?? '',
      comment: r.comment ?? '',
    })),
  }
}

export function segFromForm(form) {
  return {
    id: form.id.trim(),
    name: form.name.trim(),
    interfaces: [...form.ports],
    address: form.address.trim(),
    dhcp: {
      enabled: Boolean(form.dhcpEnabled),
      pool_start: form.dhcpEnabled ? form.poolStart.trim() || null : null,
      pool_end: form.dhcpEnabled ? form.poolEnd.trim() || null : null,
      lease_hours: Number(form.leaseHours) || 12,
      dns: form.dhcpEnabled ? splitList(form.dnsText) : [],
    },
    reservations: form.reservations
      .filter((r) => r.mac.trim() && r.ip.trim())
      .map((r) => ({
        mac: r.mac.trim().toLowerCase(),
        ip: r.ip.trim(),
        hostname: r.hostname.trim() || null,
        comment: r.comment.trim() || null,
      })),
  }
}

export function policyToForm(policy) {
  const ping = policy?.ping_check
  return {
    priority: policy?.priority ?? '',
    weight: policy?.weight ?? 1,
    pingEnabled: ping?.enabled ?? false,
    target: ping?.target ?? '1.1.1.1',
    intervalS: ping?.interval_s ?? 30,
    failThreshold: ping?.fail_threshold ?? 3,
  }
}

export function policyFromForm(form) {
  return {
    priority: form.priority === '' || form.priority === null ? null : Number(form.priority),
    weight: Number(form.weight) || 1,
    ping_check: {
      enabled: Boolean(form.pingEnabled),
      target: form.target.trim() || '1.1.1.1',
      interval_s: Number(form.intervalS) || 30,
      fail_threshold: Number(form.failThreshold) || 3,
    },
  }
}

export function routeToForm(route) {
  return {
    dest: route?.dest ?? '',
    gateway: route?.gateway ?? '',
    metric: route?.metric ?? '',
  }
}

export function routeFromForm(form) {
  return {
    dest: form.dest.trim(),
    gateway: form.gateway.trim(),
    metric: form.metric === '' || form.metric === null ? null : Number(form.metric),
  }
}

function splitList(text) {
  if (!text) {
    return []
  }
  return String(text)
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}
