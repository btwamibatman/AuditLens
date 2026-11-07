<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, tokenStore } from '@/lib/api'
import type { TokenResponse } from '@/types'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; authenticated: [user: TokenResponse['user']] }>()
const mode = ref<'login' | 'register'>('login')
const form = ref({ email: '', password: '', name: '' })
const error = ref('')
const busy = ref(false)

watch(mode, () => { error.value = '' })

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const path = mode.value === 'login' ? '/auth/login' : '/auth/register'
    const result = await api.post<TokenResponse>(path, mode.value === 'login' ? { email: form.value.email, password: form.value.password } : form.value)
    tokenStore.set(result.access_token)
    emit('authenticated', result.user)
    emit('close')
  } catch (value) {
    error.value = value instanceof Error ? value.message : 'Ошибка авторизации'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="open" class="overlay" @click.self="emit('close')"><form class="panel modal" @submit.prevent="submit"><div class="row between"><h2>{{ mode === 'login' ? 'Вход' : 'Регистрация' }}</h2><button type="button" class="button button--ghost" @click="emit('close')">✕</button></div><div class="row"><button type="button" class="button" @click="mode = 'login'">Войти</button><button type="button" class="button" @click="mode = 'register'">Регистрация</button></div><label v-if="mode === 'register'" class="field">Имя<input v-model="form.name" class="input" /></label><label class="field">Email<input v-model="form.email" class="input" type="email" required /></label><label class="field">Пароль<input v-model="form.password" class="input" type="password" required /></label><p v-if="error" class="error-message">{{ error }}</p><button class="button button--primary full-width" :disabled="busy">{{ busy ? 'Подождите…' : mode === 'login' ? 'Войти' : 'Создать аккаунт' }}</button></form></div>
</template>
