import { t } from '../i18n'

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return '—'
  }
  const units = [t('fmt.b'), t('fmt.kb'), t('fmt.mb'), t('fmt.gb'), t('fmt.tb')]
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1
  return `${value.toFixed(digits)} ${units[unit]}`
}

export function formatRate(bytesPerSec) {
  if (!Number.isFinite(bytesPerSec) || bytesPerSec < 0) {
    return '—'
  }
  return `${formatBytes(bytesPerSec)}${t('fmt.perSec')}`
}

export function formatUptime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return '—'
  }
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const parts = []
  if (days > 0) {
    parts.push(`${days} ${t('fmt.d')}`)
  }
  if (days > 0 || hours > 0) {
    parts.push(`${hours} ${t('fmt.h')}`)
  }
  parts.push(`${minutes} ${t('fmt.min')}`)
  return parts.join(' ')
}
