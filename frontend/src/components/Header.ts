import { escapeHtml } from '@/lib/dom'
import { store, type AppState } from '@/state/store'

export function renderHeader(container: HTMLElement) {
  let prevTab: string | null = null
  let prevToast: string | null = null

  store.subscribe((state: AppState) => {
    const toastKey = state.toast ? `${state.toast.type}:${state.toast.message}` : ''
    if (state.activeTab === prevTab && toastKey === prevToast) return
    prevTab = state.activeTab
    prevToast = toastKey

    container.innerHTML = `
      <header class="border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md sticky top-0 z-30 shrink-0">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div class="flex items-center gap-3">
            <div class="w-9 h-9 rounded-xl bg-emerald-600 flex items-center justify-center text-white font-black text-lg shadow-xs">
              A
            </div>
            <div>
              <div class="flex items-center gap-2.5">
                <span class="font-extrabold text-lg tracking-tight text-slate-900 dark:text-white">AuditLens</span>
                <span class="text-xs font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300">
                  CQA Hackathon
                </span>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-2.5">
            <button
              id="tab-btn-workspace"
              class="px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                state.activeTab === 'workspace'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
              }"
            >
              💬 Диалоги и оценка
            </button>
            <button
              id="tab-btn-checklists"
              class="px-4 py-2 rounded-lg text-sm font-semibold transition-all ${
                state.activeTab === 'checklists'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
              }"
            >
              ⚙️ Редактор чек-листа
            </button>
          </div>
        </div>

        ${
          state.toast
            ? `
          <div class="border-t px-4 py-2.5 text-sm font-medium flex items-center justify-between ${
            state.toast.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
              : 'bg-red-50 text-red-800 border-red-200'
          }">
            <span>${escapeHtml(state.toast.message)}</span>
            <button id="toast-close" class="text-sm font-bold opacity-60 hover:opacity-100">&times;</button>
          </div>
        `
            : ''
        }
      </header>
    `

    container.querySelector('#tab-btn-workspace')?.addEventListener('click', () => {
      store.setState({ activeTab: 'workspace' })
    })

    container.querySelector('#tab-btn-checklists')?.addEventListener('click', () => {
      store.setState({ activeTab: 'checklists' })
    })

    container.querySelector('#toast-close')?.addEventListener('click', () => {
      store.setState({ toast: null })
    })
  })
}

