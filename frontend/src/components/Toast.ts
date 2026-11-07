import { escapeHtml } from '@/lib/dom'
import { store, type AppState } from '@/state/store'

export function renderToast(container: HTMLElement) {
  let prevToast: string | null = null

  store.subscribe((state: AppState) => {
    const toastKey = state.toast ? `${state.toast.type}:${state.toast.message}` : ''
    if (toastKey === prevToast) return
    prevToast = toastKey

    if (!state.toast) {
      container.innerHTML = ''
      return
    }

    const isSuccess = state.toast.type === 'success'

    container.innerHTML = `
      <div
        id="cqa-floating-toast"
        role="alert"
        class="pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl shadow-xl border text-sm font-medium transition-all duration-300 transform translate-y-0 opacity-100 ${
          isSuccess
            ? 'bg-white dark:bg-slate-900 border-emerald-500/30 text-slate-800 dark:text-slate-100 ring-1 ring-emerald-500/20'
            : 'bg-white dark:bg-slate-900 border-red-500/30 text-slate-800 dark:text-slate-100 ring-1 ring-red-500/20'
        }"
      >
        <div class="w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
          isSuccess ? 'bg-emerald-500 text-white' : 'bg-red-500 text-white'
        }">
          <span class="material-symbols-outlined text-[16px]">${isSuccess ? 'check' : 'priority_high'}</span>
        </div>

        <div class="flex-1 text-[13.5px] leading-snug">
          ${escapeHtml(state.toast.message)}
        </div>

        <button
          id="floating-toast-close"
          class="shrink-0 p-1 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors inline-flex items-center justify-center"
          title="Закрыть"
        >
          <span class="material-symbols-outlined text-[18px]">close</span>
        </button>
      </div>
    `

    container.querySelector('#floating-toast-close')?.addEventListener('click', () => {
      store.setState({ toast: null })
    })
  })
}

