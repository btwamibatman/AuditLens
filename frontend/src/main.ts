import './styles/global.css'
import { renderHeader } from '@/components/Header'
import { cqaApi } from '@/features/cqa/api'
import { renderChecklistEditor } from '@/features/cqa/components/ChecklistEditor'
import { renderConversationList } from '@/features/cqa/components/ConversationList'
import { renderEvaluationCard } from '@/features/cqa/components/EvaluationCard'
import { renderTranscriptView } from '@/features/cqa/components/TranscriptView'
import { store, type AppState } from '@/state/store'

function initApp() {
  const root = document.getElementById('app')
  if (!root) {
    console.error('Root element #app not found')
    return
  }

  root.className = 'font-sans h-screen w-screen flex flex-col overflow-hidden bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 text-sm antialiased'

  root.innerHTML = `
    <div id="app-header"></div>
    <main id="app-main" class="flex-1 overflow-hidden p-3 sm:p-4 max-w-7xl w-full mx-auto"></main>
  `

  const headerContainer = document.getElementById('app-header')!
  const mainContainer = document.getElementById('app-main')!

  renderHeader(headerContainer)

  let currentTab: string | null = null

  store.subscribe((state: AppState) => {
    if (state.activeTab === currentTab) return
    currentTab = state.activeTab

    mainContainer.innerHTML = ''

    if (state.activeTab === 'workspace') {
      mainContainer.innerHTML = `
        <div class="h-full flex flex-col md:flex-row bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xs overflow-hidden">
          <!-- Левая колонка: список диалогов -->
          <div id="pane-conv-list" class="w-full md:w-80 h-full"></div>

          <!-- Центральная колонка: транскрипт -->
          <div id="pane-transcript" class="flex-1 h-full border-t md:border-t-0 md:border-r border-slate-200 dark:border-slate-800"></div>

          <!-- Правая колонка: оценка и апелляции -->
          <div id="pane-evaluation" class="w-full md:w-96 lg:w-[420px] h-full border-t md:border-t-0 border-slate-200 dark:border-slate-800"></div>
        </div>
      `

      renderConversationList(document.getElementById('pane-conv-list')!)
      renderTranscriptView(document.getElementById('pane-transcript')!)
      renderEvaluationCard(document.getElementById('pane-evaluation')!)
    } else if (state.activeTab === 'checklists') {
      const editorWrapper = document.createElement('div')
      editorWrapper.className = 'h-full'
      mainContainer.appendChild(editorWrapper)
      renderChecklistEditor(editorWrapper)
    }
  })

  // Загружаем начальный активный чек-лист в глобальный store
  void cqaApi.listChecklists().then((list) => {
    store.setState({
      checklists: list,
      activeChecklist: list.find((c) => c.is_active) || list[0] || null,
      selectedChecklistId: (list.find((c) => c.is_active) || list[0])?.id || null,
    })
  })
}

// Запуск приложения
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp)
} else {
  initApp()
}
