import { store, type AppState } from '@/state/store'

export function renderHeader(container: HTMLElement) {
  let prevTab: string | null = null
  let prevTheme: string | null = null

  store.subscribe((state: AppState) => {
    if (state.activeTab === prevTab && state.theme === prevTheme) return
    prevTab = state.activeTab
    prevTheme = state.theme
    const isDark = state.theme === 'dark'

    container.innerHTML = `
      <header class="border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md sticky top-0 z-30 shrink-0">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
          <div></div>

          <div class="flex items-center gap-2.5">
            <button
              id="tab-btn-workspace"
              class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold transition-all ${
                state.activeTab === 'workspace'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white'
              }"
            >
              <span class="material-symbols-outlined text-[18px]">forum</span>
              <span>Диалоги и оценка</span>
            </button>
            <button
              id="tab-btn-checklists"
              class="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold transition-all ${
                state.activeTab === 'checklists'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white'
              }"
            >
              <span class="material-symbols-outlined text-[18px]">tune</span>
              <span>Редактор чек-листа</span>
            </button>

            <div class="h-6 w-px bg-slate-200 dark:bg-slate-800 mx-0.5"></div>

            <button
              id="theme-toggle-btn"
              type="button"
              title="${isDark ? 'Включить светлую тему' : 'Включить тёмную тему'}"
              aria-label="${isDark ? 'Включить светлую тему' : 'Включить тёмную тему'}"
              class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 transition-all cursor-pointer"
            >
              <span class="material-symbols-outlined text-[18px] ${isDark ? 'text-amber-400' : 'text-slate-600'}">${
                isDark ? 'light_mode' : 'dark_mode'
              }</span>
              <span class="hidden sm:inline">${isDark ? 'Светлая' : 'Тёмная'}</span>
            </button>
          </div>
        </div>
      </header>
    `

    container.querySelector('#tab-btn-workspace')?.addEventListener('click', () => {
      store.setState({ activeTab: 'workspace' })
    })

    container.querySelector('#tab-btn-checklists')?.addEventListener('click', () => {
      store.setState({ activeTab: 'checklists' })
    })

    container.querySelector('#theme-toggle-btn')?.addEventListener('click', () => {
      store.toggleTheme()
    })
  })
}
