import { formatDistanceToNow, format as formatDate } from 'date-fns'
import { enUS, fr } from 'date-fns/locale'

const LOCALES = { fr, en: enUS }

export function dateLocale(language) {
  return LOCALES[language?.slice(0, 2)] ?? fr
}

/** `mm:ss`, or `h:mm:ss` past an hour — the convention every player uses. */
export function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds || 0))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = seconds % 60
  const pad = (n) => String(n).padStart(2, '0')
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`
}

/** Compact counts: 1 234 -> 1,2 k. Uses the locale's own separators. */
export function formatCount(value, language = 'fr') {
  const n = Number(value || 0)
  return new Intl.NumberFormat(language === 'en' ? 'en-US' : 'fr-FR', {
    notation: n >= 10000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(n)
}

export function formatBytes(bytes, language = 'fr') {
  const value = Number(bytes || 0)
  if (value === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const scaled = value / 1024 ** exponent
  return `${new Intl.NumberFormat(language === 'en' ? 'en-US' : 'fr-FR', {
    maximumFractionDigits: scaled < 10 ? 1 : 0,
  }).format(scaled)} ${units[exponent]}`
}

export function formatRelative(dateish, language = 'fr') {
  if (!dateish) return ''
  return formatDistanceToNow(new Date(dateish), {
    addSuffix: true,
    locale: dateLocale(language),
  })
}

export function formatAbsolute(dateish, language = 'fr') {
  if (!dateish) return ''
  return formatDate(new Date(dateish), 'PPP', { locale: dateLocale(language) })
}

export function formatBitrate(kbps) {
  return kbps >= 1000 ? `${(kbps / 1000).toFixed(1)} Mbps` : `${kbps} kbps`
}
