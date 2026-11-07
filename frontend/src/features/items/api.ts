import { api, type Page } from '@/lib/api'
import type { Item, ItemCreate, ItemStatus, ItemUpdate } from '@/types'

export const itemsApi = {
  list: (params?: { q?: string; status?: ItemStatus; limit?: number; offset?: number }) =>
    api.get<Page<Item>>('/items', { query: params }),

  get: (id: number) => api.get<Item>(`/items/${id}`),

  create: (data: ItemCreate) => api.post<Item>('/items', data),

  update: (id: number, data: ItemUpdate) => api.patch<Item>(`/items/${id}`, data),

  delete: (id: number) => api.delete(`/items/${id}`),
}
