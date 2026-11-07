import { cqaApi } from '@/features/cqa/api'
import { escapeHtml } from '@/lib/dom'
import { store, type AppState } from '@/state/store'
import type { ConversationImport, ConversationSummary } from '@/types/cqa'

export function renderConversationList(container: HTMLElement) {
  let fileInput: HTMLInputElement | null = null
  let shellRendered = false

  async function loadConversations() {
    store.setState({ loadingList: true, listError: null })
    try {
      const list = await cqaApi.listConversations()
      store.setState({ conversations: list })
      const curr = store.getState().selectedConversationId
      if (!curr && list.length > 0) {
        void selectConversation(list[0].id)
      }
    } catch (err: any) {
      store.setState({ listError: err.message || 'Ошибка загрузки диалогов' })
    } finally {
      store.setState({ loadingList: false })
    }
  }

  async function selectConversation(id: string) {
    store.setState({
      selectedConversationId: id,
      loadingConv: true,
      highlightedIndex: null,
      highlightedRange: null,
      currentEvaluation: null,
      appeals: [],
    })
    try {
      const conv = await cqaApi.getConversation(id)
      store.setState({ selectedConversation: conv })
      // Загружаем существующие оценки
      const history = await cqaApi.listEvaluations(id)
      store.setState({ evaluationHistory: history })
      if (history.length > 0) {
        const latest = await cqaApi.getEvaluation(history[0].id)
        store.setState({ currentEvaluation: latest })
        const appeals = await cqaApi.listAppeals(latest.id)
        store.setState({ appeals })
      }
    } catch (err: any) {
      store.showToast('error', err.message || 'Не удалось открыть диалог')
    } finally {
      store.setState({ loadingConv: false })
    }
  }

  async function onSyncDev() {
    store.setState({ syncLoading: true, syncMsg: null })
    try {
      const res = await cqaApi.syncDataset('DEV')
      store.showToast('success', `Синхронизировано DEV: создано ${res.created}, обновлено ${res.updated}`)
      await loadConversations()
    } catch (err: any) {
      store.showToast('error', err.message || 'Ошибка синхронизации датасета')
    } finally {
      store.setState({ syncLoading: false })
    }
  }

  async function handleFileImport(e: Event) {
    const target = e.target as HTMLInputElement
    const file = target.files?.[0]
    if (!file) return
    store.setState({ syncLoading: true })
    try {
      const text = await file.text()
      const raw = JSON.parse(text)
      const payload: ConversationImport = {
        dataset_group: raw.data?.dataset_group_id || raw.dataset_group || 'DEV',
        records: raw.data?.records || raw.records || (Array.isArray(raw) ? raw : []),
      }
      if (!payload.records.length) {
        throw new Error('В файле не найдено массива records')
      }
      const res = await cqaApi.importConversations(payload)
      store.showToast('success', `Импортировано: создано ${res.created}, обновлено ${res.updated}`)
      await loadConversations()
    } catch (err: any) {
      store.showToast('error', `Ошибка импорта: ${err.message}`)
    } finally {
      store.setState({ syncLoading: false })
      target.value = ''
    }
  }

  function renderShell() {
    container.innerHTML = `
      <div class="h-full flex flex-col bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 shrink-0">
        <!-- Поиск и синхронизация -->
        <div class="p-4 border-b border-slate-200 dark:border-slate-800 space-y-3">
          <div class="flex items-center gap-2">
            <input
              id="cqa-search-input"
              type="text"
              placeholder="Поиск по ID диалога..."
              class="flex-1 text-sm px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-emerald-500 font-medium"
            />
            <button
              id="cqa-sync-btn"
              title="Синхронизировать DEV"
              class="px-2.5 py-2 rounded-lg text-sm font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
            >
              🔄
            </button>
            <button
              id="cqa-import-btn"
              title="Импортировать invoke.json"
              class="px-2.5 py-2 rounded-lg text-sm font-semibold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:bg-slate-200"
            >
              📥
            </button>
            <input type="file" id="cqa-file-picker" accept=".json" class="hidden" />
          </div>

          <!-- Фильтры: язык -->
          <div class="flex items-center justify-between text-xs text-slate-500">
            <span class="font-bold text-slate-700 dark:text-slate-300">Язык:</span>
            <div class="flex gap-1" id="cqa-lang-filters">
              ${['ALL', 'RU', 'KZ', 'EN']
                .map(
                  (l) => `
                <button data-lang="${l}" class="px-2.5 py-1 rounded text-xs font-bold transition-colors bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200">
                  ${l}
                </button>
              `,
                )
                .join('')}
            </div>
          </div>

          <!-- Фильтры: канал -->
          <div class="flex items-center justify-between text-xs text-slate-500">
            <span class="font-bold text-slate-700 dark:text-slate-300">Канал:</span>
            <div class="flex gap-1" id="cqa-channel-filters">
              ${[
                { id: 'ALL', label: 'Все' },
                { id: 'CHAT', label: 'Чат' },
                { id: 'CALL', label: 'Звонок' },
              ]
                .map(
                  (c) => `
                <button data-channel="${c.id}" class="px-2.5 py-1 rounded text-xs font-bold transition-colors bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200">
                  ${c.label}
                </button>
              `,
                )
                .join('')}
            </div>
          </div>
        </div>

        <!-- Список диалогов -->
        <div id="cqa-items-container" class="flex-1 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800"></div>
      </div>
    `

    const searchInput = container.querySelector('#cqa-search-input') as HTMLInputElement | null
    searchInput?.addEventListener('input', (e) => {
      store.setState({ searchQuery: (e.target as HTMLInputElement).value })
    })

    container.querySelector('#cqa-sync-btn')?.addEventListener('click', () => {
      void onSyncDev()
    })

    fileInput = container.querySelector('#cqa-file-picker') as HTMLInputElement | null
    fileInput?.addEventListener('change', handleFileImport)

    container.querySelector('#cqa-import-btn')?.addEventListener('click', () => {
      fileInput?.click()
    })

    container.querySelectorAll('#cqa-lang-filters button').forEach((btn) => {
      btn.addEventListener('click', () => {
        const lang = btn.getAttribute('data-lang') || 'ALL'
        store.setState({ selectedLanguage: lang })
      })
    })

    container.querySelectorAll('#cqa-channel-filters button').forEach((btn) => {
      btn.addEventListener('click', () => {
        const ch = btn.getAttribute('data-channel') || 'ALL'
        store.setState({ selectedChannel: ch })
      })
    })

    shellRendered = true
  }

  store.subscribe((state: AppState) => {
    if (!shellRendered) {
      renderShell()
    }

    // Обновляем фильтры языка
    container.querySelectorAll('#cqa-lang-filters button').forEach((btn) => {
      const l = btn.getAttribute('data-lang')
      if (l === state.selectedLanguage) {
        btn.className = 'px-2 py-0.5 rounded text-[11px] font-semibold transition-colors bg-emerald-600 text-white'
      } else {
        btn.className = 'px-2 py-0.5 rounded text-[11px] font-semibold transition-colors bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
      }
    })

    // Обновляем фильтры канала
    container.querySelectorAll('#cqa-channel-filters button').forEach((btn) => {
      const ch = btn.getAttribute('data-channel')
      if (ch === state.selectedChannel) {
        btn.className = 'px-2 py-0.5 rounded text-[11px] font-semibold transition-colors bg-emerald-600 text-white'
      } else {
        btn.className = 'px-2 py-0.5 rounded text-[11px] font-semibold transition-colors bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
      }
    })

    const syncBtn = container.querySelector('#cqa-sync-btn') as HTMLButtonElement | null
    if (syncBtn) {
      syncBtn.disabled = state.syncLoading
      syncBtn.textContent = state.syncLoading ? '⏳' : '🔄'
    }

    const itemsContainer = container.querySelector('#cqa-items-container')
    if (!itemsContainer) return

    const filtered = state.conversations.filter((c: ConversationSummary) => {
      if (state.selectedLanguage !== 'ALL' && c.language !== state.selectedLanguage) return false
      if (state.selectedChannel !== 'ALL') {
        const isCall = c.channel.toLowerCase().includes('call') || c.channel.toLowerCase().includes('voice')
        if (state.selectedChannel === 'CALL' && !isCall) return false
        if (state.selectedChannel === 'CHAT' && isCall) return false
      }
      if (state.searchQuery.trim()) {
        const q = state.searchQuery.toLowerCase()
        return c.id.toLowerCase().includes(q)
      }
      return true
    })

    if (state.loadingList) {
      itemsContainer.innerHTML = `
        <div class="p-6 text-center text-xs text-slate-400">
          <div class="inline-block animate-spin text-lg mb-2">🔄</div>
          <div>Загрузка диалогов...</div>
        </div>
      `
      return
    }

    if (filtered.length === 0) {
      itemsContainer.innerHTML = `
        <div class="p-6 text-center text-xs text-slate-400">
          Диалоги не найдены
        </div>
      `
      return
    }

    itemsContainer.innerHTML = filtered
      .map((item: ConversationSummary) => {
        const isSelected = item.id === state.selectedConversationId
        const isCall =
          item.channel.toLowerCase().includes('call') ||
          item.channel.toLowerCase().includes('voice')
        return `
          <div
            data-conv-id="${escapeHtml(item.id)}"
            class="cqa-conv-item p-3.5 cursor-pointer transition-colors ${
              isSelected
                ? 'bg-emerald-50/80 dark:bg-emerald-950/40 border-l-4 border-emerald-500'
                : 'hover:bg-slate-50 dark:hover:bg-slate-800/60'
            }"
          >
            <div class="flex items-center justify-between mb-1.5">
              <span class="font-mono text-[13.5px] font-bold text-slate-900 dark:text-slate-100 truncate">
                ${escapeHtml(item.id)}
              </span>
              <span class="text-xs font-bold px-2 py-0.5 rounded ${
                item.language === 'RU'
                  ? 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300'
                  : item.language === 'KZ'
                    ? 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300'
                    : 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300'
              }">
                ${escapeHtml(item.language)}
              </span>
            </div>
            <div class="flex items-center justify-between text-xs text-slate-400 font-medium">
              <span class="flex items-center gap-1.5">
                ${isCall ? '📞 Звонок' : '💬 Чат'}
                ${item.audio_url ? '• 🎵' : ''}
              </span>
              <span>${item.dataset_group}</span>
            </div>
          </div>
        `
      })
      .join('')

    itemsContainer.querySelectorAll('.cqa-conv-item').forEach((el) => {
      el.addEventListener('click', () => {
        const id = el.getAttribute('data-conv-id')
        if (id) void selectConversation(id)
      })
    })
  })

  // Первоначальная загрузка диалогов
  void loadConversations()
}
