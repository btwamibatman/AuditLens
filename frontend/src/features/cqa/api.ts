import { api } from '@/lib/api'
import type {
  AppealCreate,
  AppealRead,
  AppealReview,
  ChecklistConfig,
  ChecklistCreate,
  ChecklistRead,
  ChecklistUpdate,
  ConversationImport,
  ConversationRead,
  ConversationSummary,
  EvaluationRead,
  EvaluationSummary,
  ImportResult,
} from '@/types/cqa'

export const cqaApi = {
  // Диалоги
  listConversations: (params?: { dataset_group?: string; language?: string }) =>
    api.get<ConversationSummary[]>('/conversations', { query: params }),

  getConversation: (id: string) =>
    api.get<ConversationRead>(`/conversations/${encodeURIComponent(id)}`),

  syncDataset: (groupId = 'DEV') =>
    api.post<ImportResult>(`/conversations/sync?group_id=${encodeURIComponent(groupId)}`),

  importConversations: (data: ConversationImport) =>
    api.post<ImportResult>('/conversations/import', data),

  // Чек-листы
  listChecklists: () =>
    api.get<ChecklistRead[]>('/checklists'),

  getActiveChecklist: () =>
    api.get<ChecklistRead>('/checklists/active'),

  getDefaultConfig: () =>
    api.get<ChecklistConfig>('/checklists/default-config'),

  createChecklist: (data: ChecklistCreate) =>
    api.post<ChecklistRead>('/checklists', data),

  updateChecklist: (id: number, data: ChecklistUpdate) =>
    api.put<ChecklistRead>(`/checklists/${id}`, data),

  activateChecklist: (id: number) =>
    api.post<ChecklistRead>(`/checklists/${id}/activate`),

  // Оценки
  evaluate: (conversationId: string, checklistId?: number | null) =>
    api.post<EvaluationRead>('/evaluations', {
      conversation_id: conversationId,
      checklist_id: checklistId ?? undefined,
    }),

  listEvaluations: (conversationId?: string, checklistId?: number) =>
    api.get<EvaluationSummary[]>('/evaluations', {
      query: { conversation_id: conversationId, checklist_id: checklistId },
    }),

  getEvaluation: (id: number) =>
    api.get<EvaluationRead>(`/evaluations/${id}`),

  // Апелляции
  createAppeal: (data: AppealCreate) =>
    api.post<AppealRead>('/appeals', data),

  listAppeals: (evaluationId?: number, status?: string) =>
    api.get<AppealRead[]>('/appeals', {
      query: { evaluation_id: evaluationId, status },
    }),

  reviewAppeal: (appealId: number, data: AppealReview) =>
    api.post<EvaluationRead>(`/appeals/${appealId}/review`, data),
}

