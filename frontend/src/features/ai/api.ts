import { api } from '@/lib/api'
import type { ChatMessage, ChatResponse } from '@/types'

export const aiApi = {
  chat: (messages: ChatMessage[], system?: string, temperature = 0.7) =>
    api.post<ChatResponse>('/ai/chat', { messages, system, temperature }),
}
