<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, tokenStore } from '@/lib/api'
import type { AppMeta, User } from '@/types'
import ItemsPage from '@/features/items/ItemsPage.vue'
import AIPage from '@/features/ai/AIPage.vue'
import UploadsPage from '@/features/uploads/UploadsPage.vue'
import AuthDialog from '@/features/auth/AuthDialog.vue'

type Tab = 'example' | 'ai' | 'uploads'
const meta = ref<AppMeta | null>(null)
const healthy = ref<boolean | null>(null)
const currentTab = ref<Tab>('example')
const user = ref<User | null>(null)
const authOpen = ref(false)

const navItems = computed(() => [
  { key: 'example' as const, label: 'Пример CRUD', icon: '▤' },
  ...(meta.value?.features.ai ? [{ key: 'ai' as const, label: 'AI-пример', icon: '✦' }] : []),
  ...(meta.value?.features.uploads ? [{ key: 'uploads' as const, label: 'Загрузка файлов', icon: '⇧' }] : []),
])

async function loadMeta() {
  try {
    const [appMeta, health] = await Promise.all([
      api.get<AppMeta>('/meta'),
      api.get<{ status: string }>('/health').catch(() => null),
    ])
    meta.value = appMeta
    healthy.value = health?.status === 'ok'
    if (appMeta.features.auth && tokenStore.get()) {
      try {
        user.value = await api.get<User>('/auth/me')
      } catch {
        tokenStore.set(null)
      }
    }
  } catch {
    healthy.value = false
  }
}

function logout() {
  tokenStore.set(null)
  user.value = null
}

onMounted(() => {
  void loadMeta()
  window.addEventListener('auth:logout', logout)
})
onUnmounted(() => window.removeEventListener('auth:logout', logout))
</script>

<template>
  <div class="app-layout">
    <aside class="app-sidebar">
      <div>
        <div class="app-brand">
          <div class="app-brand__icon">✦</div>
          <div>
            <div class="app-brand__title">{{ meta?.app_name || 'Launchpad' }}</div>
            <div class="small faint">{{ meta?.environment || 'dev' }} · Vue</div>
          </div>
        </div>
        <nav class="app-nav">
          <button v-for="item in navItems" :key="item.key" class="app-nav__item" :class="{ 'app-nav__item--active': currentTab === item.key }" @click="currentTab = item.key">
            <span class="nav-icon">{{ item.icon }}</span><span class="grow">{{ item.label }}</span>
          </button>
          <a href="/api/docs" target="_blank" rel="noreferrer" class="app-nav__item"><span class="nav-icon">↗</span><span class="grow">FastAPI Docs</span></a>
        </nav>
      </div>
      <div class="app-sidebar__bottom">
        <div class="row between"><span class="muted">Backend</span><span class="badge" :class="healthy ? 'badge--ok' : 'badge--error'">{{ healthy === null ? 'Проверка…' : healthy ? 'Online' : 'Offline' }}</span></div>
        <div v-if="meta?.features.auth" class="auth-box">
          <template v-if="user"><span class="small">{{ user.name || user.email }}</span><button class="button button--ghost" @click="logout">Выйти</button></template>
          <button v-else class="button button--secondary full-width" @click="authOpen = true">Войти / регистрация</button>
        </div>
        <div class="small faint center">FastAPI · Vue 3 · TypeScript</div>
      </div>
    </aside>

    <main class="app-main">
      <ItemsPage v-if="currentTab === 'example'" />
      <AIPage v-else-if="currentTab === 'ai' && meta?.features.ai" />
      <UploadsPage v-else-if="currentTab === 'uploads' && meta?.features.uploads" />
    </main>

    <AuthDialog v-if="meta?.features.auth" :open="authOpen" @close="authOpen = false" @authenticated="user = $event" />
  </div>
</template>

<style>
#app { min-height: 100%; }
.app-layout { display:flex; min-height:100vh; }
.app-sidebar { width:var(--sidebar-w); flex-shrink:0; background:var(--bg-elevated); border-right:1px solid var(--border); display:flex; flex-direction:column; justify-content:space-between; padding:20px 16px; position:sticky; top:0; height:100vh; }
.app-brand { display:flex; align-items:center; gap:12px; padding:8px 10px; margin-bottom:20px; }
.app-brand__icon { width:36px; height:36px; border-radius:10px; background:var(--gradient); display:grid; place-items:center; color:white; box-shadow:var(--shadow-glow); }
.app-brand__title { font-weight:750; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.app-nav { display:flex; flex-direction:column; gap:4px; }
.app-nav__item { display:flex; align-items:center; gap:10px; width:100%; padding:10px 12px; border:0; border-radius:9px; color:var(--text-muted); background:transparent; text-align:left; font:inherit; cursor:pointer; }
.app-nav__item:hover,.app-nav__item--active { color:var(--text); background:var(--surface-hover); }
.app-sidebar__bottom { display:flex; flex-direction:column; gap:12px; }
.app-main { width:100%; max-width:1500px; margin:0 auto; padding:36px clamp(20px,4vw,56px); }
.page-header { display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:26px; }
.page-header h1 { margin:3px 0 8px; }
.eyebrow { color:var(--accent-2); font:600 .72rem var(--font-mono); letter-spacing:.12em; }
.muted { color:var(--text-muted); }.faint { color:var(--text-faint); }.small { font-size:.82rem; }.center { text-align:center; }
.row { display:flex; align-items:center; gap:10px; }.row.between { justify-content:space-between; }.row.end { justify-content:flex-end; }.grow { flex:1; }.nav-icon { width:22px; text-align:center; font-size:1.1rem; }
.panel { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:18px; }
.button { border:1px solid var(--border); border-radius:9px; padding:9px 13px; color:var(--text); background:var(--surface-strong); font:inherit; cursor:pointer; }.button:hover { background:var(--surface-hover); }.button:disabled { opacity:.55; cursor:not-allowed; }
.button--primary { color:#fff; background:var(--accent); border-color:transparent; font-weight:600; }.button--secondary { background:var(--surface-strong); }.button--ghost { background:transparent; }.danger,.error-message { color:var(--danger); }.full-width { width:100%; }
.stats-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin-bottom:18px; }.stat { display:flex; flex-direction:column; gap:10px; }.stat strong { font-size:1.8rem; }
.filters { display:flex; gap:12px; margin-bottom:18px; }.input { width:100%; min-width:0; border:1px solid var(--border-strong); border-radius:9px; padding:10px 12px; color:var(--text); background:var(--bg-elevated); font:inherit; }.select { max-width:220px; }
.items-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr)); gap:14px; }.item-card { display:flex; flex-direction:column; gap:14px; }.item-card h2 { font-size:1.1rem; }.description { min-height:36px; white-space:pre-wrap; }.card-actions { border-top:1px solid var(--border); padding-top:12px; margin-top:auto; }
.status-pill,.badge { border:1px solid var(--border); border-radius:999px; padding:4px 9px; background:var(--surface-strong); color:var(--text); font:inherit; font-size:.78rem; }.status-pill { cursor:pointer; }.badge--ok { color:var(--success); }.badge--error { color:var(--danger); }.empty { text-align:center; display:grid; justify-items:center; gap:12px; padding:48px 20px; }.error-message { margin:12px 0; }
.auth-box { margin:14px 0; }.auth-box:has(.small) { display:flex; align-items:center; justify-content:space-between; gap:8px; }.overlay { position:fixed; inset:0; z-index:20; display:grid; place-items:center; padding:20px; background:rgb(0 0 0 / .62); }.modal { width:min(100%,480px); display:flex; flex-direction:column; gap:16px; box-shadow:var(--shadow); }.field { display:grid; gap:6px; color:var(--text-muted); font-size:.9rem; }.textarea { resize:vertical; }
.chat-panel { padding:0; overflow:hidden; }.chat-messages { min-height:300px; max-height:55vh; overflow:auto; display:flex; flex-direction:column; gap:14px; padding:20px; }.chat-message { max-width:85%; padding:12px 14px; border-radius:12px; background:var(--surface-hover); }.chat-message--user { align-self:flex-end; background:var(--accent-soft); }.chat-message p { white-space:pre-wrap; margin-top:5px; }.chat-form { display:flex; gap:10px; border-top:1px solid var(--border); padding:14px; }.drop-zone { display:grid; place-items:center; min-height:160px; margin-bottom:18px; border-style:dashed; cursor:pointer; color:var(--text-muted); }.drop-zone--active { border-color:var(--accent); background:var(--surface-hover); }
@media(max-width:760px) { .app-layout { display:block; }.app-sidebar { position:static; height:auto; width:100%; gap:16px; }.app-sidebar__bottom { display:none; }.app-nav { flex-direction:row; overflow:auto; }.app-nav__item { white-space:nowrap; }.app-main { padding:24px 16px; }.page-header { align-items:flex-start; flex-direction:column; }.stats-grid { grid-template-columns:1fr; }.filters { flex-direction:column; }.select { max-width:none; } }
</style>
