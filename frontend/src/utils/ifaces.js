export function defaultItem(name, role = 'off') {
  return {
    name,
    role,
    ipv4: null,
    address: null,
    gateway: null,
    dns: [],
    mtu: null,
    vlan_id: null,
    mac: null,
    pppoe_username: null,
    pppoe_password: null,
  }
}

export function toForm(item) {
  return {
    name: item?.name ?? '',
    role: item?.role ?? 'off',
    ipv4: item?.role === 'lan' ? 'static' : (item?.ipv4 ?? 'dhcp'),
    address: item?.address ?? '',
    gateway: item?.gateway ?? '',
    dnsText: (item?.dns ?? []).join(', '),
    mtu: item?.mtu ?? '',
    mac: item?.mac ?? '',
    pppoe_username: item?.pppoe_username ?? '',
    pppoe_password: item?.pppoe_password ?? '',
  }
}

export function fromForm(form) {
  const item = {
    name: form.name,
    role: form.role,
    vlan_id: null,
    mac: null,
    pppoe_username: null,
    pppoe_password: null,
  }
  if (form.role === 'off') {
    return { ...item, ipv4: null, address: null, gateway: null, dns: [], mtu: null }
  }
  item.ipv4 = form.role === 'lan' ? 'static' : form.ipv4
  item.mtu = form.mtu === '' || form.mtu === null ? null : Number(form.mtu)
  item.mac = form.role === 'wan' ? ((form.mac ?? '').trim().toLowerCase() || null) : null
  item.dns = form.role === 'wan' ? splitList(form.dnsText) : []
  if (item.ipv4 === 'pppoe') {
    item.pppoe_username = (form.pppoe_username ?? '').trim() || null
    item.pppoe_password = (form.pppoe_password ?? '').trim() || null
  } else {
    item.pppoe_username = null
    item.pppoe_password = null
  }
  if (item.ipv4 === 'static') {
    item.address = (form.address ?? '').trim() || null
    item.gateway = form.role === 'wan' ? ((form.gateway ?? '').trim() || null) : null
  } else {
    item.address = null
    item.gateway = null
  }
  return item
}

export function secondsLeft(deadline, nowSeconds = Date.now() / 1000) {
  if (!Number.isFinite(deadline)) {
    return 0
  }
  return Math.max(0, Math.round(deadline - nowSeconds))
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
