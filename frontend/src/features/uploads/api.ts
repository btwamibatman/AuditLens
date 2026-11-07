import { api } from '@/lib/api'
import type { UploadFileItem } from '@/types'

export const uploadsApi = {
  list: () => api.get<UploadFileItem[]>('/uploads'),
  upload: (file: File) => api.upload<UploadFileItem>('/uploads', file),
}
