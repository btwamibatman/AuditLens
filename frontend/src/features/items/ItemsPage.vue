<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { itemsApi } from './api'
import type { Item, ItemCreate, ItemStatus, ItemUpdate } from '@/types'

const items = ref<Item[]>([])
const total = ref(0)
const search = ref('')
const statusFilter = ref('all')
const busy = ref(false)
const error = ref('')
const modalOpen = ref(false)
const editing = ref<Item | null>(null)
const form = ref<{ title: string; description: string; status: ItemStatus }>({ title: '', description: '', status: 'todo' })
let searchTimer: ReturnType<typeof setTimeout> | undefined

const inProgress = computed(() => items.value.filter((item) => item.status === 'in_progress').length)
const done = computed(() => items.value.filter((item) => item.status === 'done').length)
const statusLabels: Record<ItemStatus, string> = { todo: 'В планах', in_progress: 'В работе', done: 'Готово' }

function errorText(value: unknown) { return value instanceof Error ? value.message : 'Произошла ошибка' }

async function loadItems() {
  busy.value = true
  error.value = ''
  try {
    const page = await itemsApi.list({ q: search.value.trim() || undefined, status: statusFilter.value === 'all' ? undefined : statusFilter.value as ItemStatus })
    items.value = page.items
    total.value = page.total
  } catch (value) {
    error.value = errorText(value)
  } finally {
    busy.value = false
  }
}

function openItem(item?: Item) {
  editing.value = item ?? null
  form.value = item ? { title: item.title, description: item.description, status: item.status } : { title: '', description: '', status: 'todo' }
  error.value = ''
  modalOpen.value = true
}

async function saveItem() {
  const payload: ItemCreate = { title: form.value.title.trim(), description: form.value.description.trim(), status: form.value.status }
  if (!payload.title) { error.value = 'Название обязательно'; return }
  busy.value = true
  error.value = ''
  try {
    if (editing.value) await itemsApi.update(editing.value.id, payload satisfies ItemUpdate)
    else await itemsApi.create(payload)
    modalOpen.value = false
    await loadItems()
  } catch (value) {
    error.value = errorText(value)
  } finally {
    busy.value = false
  }
}

async function cycleStatus(item: Item) {
  const next: Record<ItemStatus, ItemStatus> = { todo: 'in_progress', in_progress: 'done', done: 'todo' }
  try { await itemsApi.update(item.id, { status: next[item.status] }); await loadItems() }
  catch (value) { error.value = errorText(value) }
}

async function deleteItem(item: Item) {
  if (!window.confirm(`Удалить «${item.title}»?`)) return
  try { await itemsApi.delete(item.id); await loadItems() }
  catch (value) { error.value = errorText(value) }
}

watch([search, statusFilter], () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => void loadItems(), 300)
}, { immediate: true })
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">STARTER FEATURE</p><h1>Пример CRUD</h1><p class="muted">Переименуй или замени этот модуль под сущность своего проекта.</p></div><button class="button button--primary" @click="openItem()">＋ Добавить запись</button></header>
  <section class="stats-grid"><article class="panel stat"><span class="muted">Всего записей</span><strong>{{ total }}</strong></article><article class="panel stat"><span class="muted">В работе</span><strong>{{ inProgress }}</strong></article><article class="panel stat"><span class="muted">Завершено</span><strong>{{ done }}</strong></article></section>
  <section class="panel filters"><input v-model="search" class="input" placeholder="Поиск по названию и описанию" /><select v-model="statusFilter" class="input select"><option value="all">Все статусы</option><option value="todo">В планах</option><option value="in_progress">В работе</option><option value="done">Готово</option></select></section>
  <p v-if="error" class="error-message">{{ error }} <button class="button button--ghost" @click="loadItems">Повторить</button></p>
  <p v-else-if="busy && !items.length" class="muted">Загрузка…</p>
  <div v-else-if="!items.length" class="panel empty"><h2>Пока нет записей</h2><p class="muted">Создай запись или замени эту демонстрационную сущность на свою.</p><button class="button button--primary" @click="openItem()">Добавить запись</button></div>
  <section v-else class="items-grid"><article v-for="item in items" :key="item.id" class="panel item-card"><div class="row between"><button class="status-pill" @click="cycleStatus(item)">{{ statusLabels[item.status] }} · сменить</button><span class="small faint">{{ new Date(item.created_at).toLocaleDateString() }}</span></div><h2>{{ item.title }}</h2><p class="muted description">{{ item.description || 'Нет описания' }}</p><div class="row between card-actions"><span class="small faint">#{{ item.id }}</span><span class="row"><button class="button button--ghost" @click="openItem(item)">Изменить</button><button class="button button--ghost danger" @click="deleteItem(item)">Удалить</button></span></div></article></section>
  <div v-if="modalOpen" class="overlay" @click.self="modalOpen = false"><form class="panel modal" @submit.prevent="saveItem"><div class="row between"><h2>{{ editing ? 'Изменить запись' : 'Новая запись' }}</h2><button type="button" class="button button--ghost" @click="modalOpen = false">✕</button></div><label class="field">Название<input v-model="form.title" class="input" required maxlength="160" /></label><label class="field">Описание<textarea v-model="form.description" class="input textarea" rows="4"></textarea></label><label class="field">Статус<select v-model="form.status" class="input select"><option value="todo">В планах</option><option value="in_progress">В работе</option><option value="done">Готово</option></select></label><p v-if="error" class="error-message">{{ error }}</p><div class="row end"><button type="button" class="button button--ghost" @click="modalOpen = false">Отмена</button><button class="button button--primary" :disabled="busy">{{ busy ? 'Сохраняю…' : 'Сохранить' }}</button></div></form></div>
</template>
