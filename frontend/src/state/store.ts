import type {
  AppealRead,
  ChecklistRead,
  ConversationRead,
  ConversationSummary,
  EvaluationRead,
  EvaluationSummary,
} from '@/types/cqa'

export interface AppState {
  activeTab: 'workspace' | 'checklists'
  conversations: ConversationSummary[]
  selectedConversationId: string | null
  selectedConversation: ConversationRead | null
  loadingList: boolean
  loadingConv: boolean
  listError: string | null
  searchQuery: string
  selectedLanguage: string
  selectedChannel: string
  checklists: ChecklistRead[]
  selectedChecklistId: number | null
  activeChecklist: ChecklistRead | null
  currentEvaluation: EvaluationRead | null
  evaluationHistory: EvaluationSummary[]
  evaluating: boolean
  evalError: string | null
  appeals: AppealRead[]
  highlightedIndex: number | null
  highlightedRange: { from: number; to: number } | null
  syncLoading: boolean
  syncMsg: string | null
  toast: { type: 'success' | 'error'; message: string } | null
}

const initialState: AppState = {
  activeTab: 'workspace',
  conversations: [],
  selectedConversationId: null,
  selectedConversation: null,
  loadingList: false,
  loadingConv: false,
  listError: null,
  searchQuery: '',
  selectedLanguage: 'ALL',
  selectedChannel: 'ALL',
  checklists: [],
  selectedChecklistId: null,
  activeChecklist: null,
  currentEvaluation: null,
  evaluationHistory: [],
  evaluating: false,
  evalError: null,
  appeals: [],
  highlightedIndex: null,
  highlightedRange: null,
  syncLoading: false,
  syncMsg: null,
  toast: null,
}

type Listener = (state: AppState) => void

class Store {
  private state: AppState = { ...initialState }
  private listeners: Set<Listener> = new Set()

  getState(): AppState {
    return this.state
  }

  setState(partial: Partial<AppState>) {
    this.state = { ...this.state, ...partial }
    this.notify()
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    listener(this.state)
    return () => this.listeners.delete(listener)
  }

  private notify() {
    for (const listener of this.listeners) {
      listener(this.state)
    }
  }

  showToast(type: 'success' | 'error', message: string, duration = 4000) {
    this.setState({ toast: { type, message } })
    setTimeout(() => {
      if (this.state.toast?.message === message) {
        this.setState({ toast: null })
      }
    }, duration)
  }
}

export const store = new Store()

