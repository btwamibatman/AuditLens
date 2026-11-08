export type Speaker = 'client' | 'operator' | 'bot' | 'system'

export interface Utterance {
  timestamp: string
  speaker: Speaker
  text: string
}

export interface ConversationSummary {
  id: string
  dataset_group: string
  channel: string
  language: string
  audio_url: string | null
  created_at: string
}

export interface ConversationRead extends ConversationSummary {
  transcript: Utterance[]
}

export interface ConversationRecord {
  conversation_id: string
  channel?: string
  language?: string
  transcript: Utterance[]
  audio_url?: string | null
}

export interface ConversationImport {
  dataset_group: string
  records: ConversationRecord[]
}

export interface ImportResult {
  dataset_group: string
  created: int_num
  updated: int_num
  total: int_num
}

type int_num = number

// ----------------- Чек-листы -----------------

export type AnswerType = 'binary' | 'scale'
export type RoundingMode = 'half_up' | 'floor' | 'ceil' | 'none'
export type CriticalPolicy = 'zero_total' | 'flag_only'

export interface ScaleLevel {
  value: number
  description: string
}

export interface Criterion {
  id: string
  name: string
  section?: string | null
  description: string
  weight: number
  answer_type: AnswerType
  scale_min: number
  scale_max: number
  scale_levels: ScaleLevel[]
  na_allowed: boolean
  na_rule?: string | null
  is_critical: boolean
  critical_rule?: string | null
  channels: ('chat' | 'call')[]
  enabled: boolean
}

export interface ScoringRules {
  total_scale: number
  rounding: RoundingMode
  rounding_digits: number
  critical_policy: CriticalPolicy
}

export interface ChecklistConfig {
  criteria: Criterion[]
  scoring: ScoringRules
  evaluator_notes: string
  explanation_language: string
}

export interface ChecklistRead {
  id: number
  name: string
  description: string
  version: number
  is_active: boolean
  config: ChecklistConfig
  created_at: string
  updated_at: string
}

export interface ChecklistCreate {
  name: string
  description?: string
  config: ChecklistConfig
}

export interface ChecklistUpdate {
  name?: string
  description?: string
  config?: ChecklistConfig
}

// ----------------- Оценки -----------------

export interface Evidence {
  message_index: number
  quote: string
  timestamp: string
  speaker: string
  verified: boolean
}

export interface CheckedRange {
  from_index: number
  to_index: number
  from_timestamp: string
  to_timestamp: string
}

export interface CriterionResult {
  criterion_id: string
  name: string
  section?: string | null
  answer_type: string
  weight: number
  scale_min: number
  scale_max: number
  is_critical: boolean
  status: 'scored' | 'na'
  score: number | null
  na_reason: string
  critical_violation: boolean
  explanation: string
  evidence: Evidence[]
  checked_range?: CheckedRange | null
  normalized?: number | null
  effective_weight: number
  points: number
  source: 'ai' | 'auto' | 'reviewer'
  warnings: string[]
}

export interface SectionResult {
  section: string
  score: number | null
  points: number
  max_points: number
}

export interface EvaluationResult {
  criteria: CriterionResult[]
  sections: SectionResult[]
  total_raw?: number | null
  total_before_critical?: number | null
  total?: number | null
  has_critical_error: boolean
  critical_criteria: string[]
  summary: string
}

export interface EvaluationRead {
  id: number
  conversation_id: string
  checklist_id: number | null
  checklist_version: number
  checklist_snapshot?: ChecklistConfig | null
  status: 'done' | 'failed' | 'pending'
  error?: string | null
  model: string
  total_score?: number | null
  has_critical_error: boolean
  input_tokens: number
  output_tokens: number
  thought_tokens: number
  cost_usd: number
  latency_ms: number
  ai_result?: EvaluationResult | null
  final_result?: EvaluationResult | null
  created_at: string
}

export interface EvaluationSummary {
  id: number
  conversation_id: string
  checklist_id: number | null
  checklist_version: number
  status: string
  model: string
  total_score?: number | null
  has_critical_error: boolean
  cost_usd: number
  created_at: string
}

// ----------------- Апелляции -----------------

export type AppealStatus = 'pending' | 'confirmed' | 'overturned'
export type Decision = 'confirm' | 'change'

export interface AppealRead {
  id: number
  evaluation_id: number
  criterion_id: string
  status: AppealStatus
  comment: string
  reviewer_comment?: string | null
  decision?: Decision | null
  new_score?: number | null
  new_is_na?: boolean | null
  new_critical_violation?: boolean | null
  created_at: string
  updated_at: string
}

export interface AppealCreate {
  evaluation_id: number
  criterion_id: string
  comment: string
}

export interface AppealReview {
  decision: Decision
  reviewer_comment: string
  new_score?: number | null
  new_is_na?: boolean
  new_na_reason?: string
  new_critical_violation?: boolean
}

