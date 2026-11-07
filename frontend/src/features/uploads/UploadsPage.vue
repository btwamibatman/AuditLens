<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { uploadsApi } from './api'
import type { UploadFileItem } from '@/types'

const files = ref<UploadFileItem[]>([])
const busy = ref(false)
const error = ref('')
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

async function loadFiles() {
  error.value = ''
  try { files.value = await uploadsApi.list() }
  catch (value) { error.value = value instanceof Error ? value.message : 'Не удалось загрузить список файлов' }
}

async function uploadFile(file?: File) {
  if (!file) return
  busy.value = true
  error.value = ''
  try { await uploadsApi.upload(file); await loadFiles() }
  catch (value) { error.value = value instanceof Error ? value.message : 'Не удалось загрузить файл' }
  finally { busy.value = false }
}

onMounted(loadFiles)
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">OPTIONAL MODULE</p><h1>Загрузка файлов</h1><p class="muted">Демонстрация upload API и локального хранения.</p></div><button class="button button--primary" :disabled="busy" @click="fileInput?.click()">{{ busy ? 'Загружаю…' : 'Выбрать файл' }}</button></header>
  <input ref="fileInput" hidden type="file" @change="uploadFile(($event.target as HTMLInputElement).files?.[0])" />
  <div class="panel drop-zone" :class="{ 'drop-zone--active': dragOver }" @click="fileInput?.click()" @dragover.prevent="dragOver = true" @dragleave="dragOver = false" @drop.prevent="dragOver = false; uploadFile($event.dataTransfer?.files[0])">Перетащи файл сюда или нажми для выбора</div>
  <p v-if="error" class="error-message">{{ error }} <button class="button button--ghost" @click="loadFiles">Обновить</button></p>
  <section v-else class="items-grid"><article v-for="file in files" :key="file.name" class="panel item-card"><h2>{{ file.name }}</h2><p class="muted">{{ file.content_type }} · {{ Math.ceil(file.size / 1024) }} КБ</p><a :href="file.url" target="_blank" rel="noreferrer">Открыть файл ↗</a></article><p v-if="!files.length" class="muted">Загруженных файлов пока нет.</p></section>
</template>
