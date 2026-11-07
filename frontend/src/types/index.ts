export type ItemStatus = 'todo' | 'in_progress' | 'done'

export interface Item {
  id: number
  title: string
  description: string
  status: ItemStatus
  created_at: string
  updated_at: string
}

export interface ItemCreate {
  title: string
  description?: string
  status?: ItemStatus
}

export interface ItemUpdate {
  title?: string
  description?: string
  status?: ItemStatus
}

export interface MetaFeatures {
  auth: boolean
  uploads: boolean
  ai: boolean
}

export interface AppMeta {
  app_name: string
  environment: string
  features: MetaFeatures
}

export interface User {
  id: number
  email: string
  name: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
}

export interface UploadFileItem {
  name: string
  url: string
  size: number
  content_type: string
  created_at: string
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  reply: string
  model: string
  mock: boolean
}
