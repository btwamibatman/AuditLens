/**
 * Безопасные утилиты для работы с DOM и экранирования строк
 */

export function escapeHtml(str: string | null | undefined): string {
  if (str === null || str === undefined) return ''
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return ''
  const trimmed = ts.trim()
  if (trimmed.includes('T')) {
    const timePart = trimmed.split('T')[1]
    if (timePart) {
      const cleanTime = timePart.split('.')[0].split('+')[0].split('-')[0].replace('Z', '')
      if (cleanTime.length >= 5) {
        return cleanTime
      }
    }
    const d = new Date(trimmed)
    if (!isNaN(d.getTime())) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    }
  }
  return trimmed
}

export function createElement<T extends HTMLElement = HTMLElement>(html: string): T {
  const template = document.createElement('template')
  template.innerHTML = html.trim()
  return template.content.firstElementChild as T
}

