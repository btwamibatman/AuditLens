<script setup lang="ts">
import { ref } from 'vue'
import { aiApi } from './api'
import type { ChatMessage } from '@/types'

const messages = ref<ChatMessage[]>([])
const prompt = ref('')
const busy = ref(false)
const error = ref('')

async function sendPrompt() {
  const content = prompt.value.trim()
  if (!content || busy.value) return
  messages.value.push({ role: 'user', content })
  prompt.value = ''
  busy.value = true
  error.value = ''
  try {
    const result = await aiApi.chat(messages.value)
    messages.value.push({ role: 'assistant', content: result.reply })
  } catch (value) {
    error.value = value instanceof Error ? value.message : 'Не удалось получить ответ'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <header class="page-header"><div><p class="eyebrow">OPTIONAL MODULE</p><h1>AI-пример</h1><p class="muted">Пример вызова OpenAI-compatible API через FastAPI.</p></div></header>
  <section class="panel chat-panel"><div class="chat-messages"><p v-if="!messages.length" class="muted">Напиши сообщение, чтобы проверить интеграцию.</p><div v-for="(message, index) in messages" :key="index" class="chat-message" :class="`chat-message--${message.role}`"><strong>{{ message.role === 'user' ? 'Ты' : 'AI' }}</strong><p>{{ message.content }}</p></div><p v-if="busy" class="muted">Генерирую ответ…</p></div><p v-if="error" class="error-message">{{ error }}</p><form class="chat-form" @submit.prevent="sendPrompt"><input v-model="prompt" class="input" :disabled="busy" placeholder="Сообщение…" /><button class="button button--primary" :disabled="busy || !prompt.trim()">Отправить</button></form></section>
</template>
