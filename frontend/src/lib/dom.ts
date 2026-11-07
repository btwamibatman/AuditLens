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

export function createElement<T extends HTMLElement = HTMLElement>(html: string): T {
  const template = document.createElement('template')
  template.innerHTML = html.trim()
  return template.content.firstElementChild as T
}

