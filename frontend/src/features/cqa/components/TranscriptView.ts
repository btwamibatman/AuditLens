import { escapeHtml, formatTimestamp } from '@/lib/dom'
import { store, type AppState } from '@/state/store'
import type { Utterance } from '@/types/cqa'

export function renderTranscriptView(container: HTMLElement) {
  store.subscribe((state: AppState) => {
    const conv = state.selectedConversation

    if (state.loadingConv) {
      container.innerHTML = `
        <div class="h-full flex items-center justify-center p-8 text-sm text-slate-400">
          <div class="text-center">
            <div class="text-2xl mb-2 text-emerald-500 animate-spin">
              <span class="material-symbols-outlined text-3xl">progress_activity</span>
            </div>
            <div>Загрузка транскрипта диалога...</div>
          </div>
        </div>
      `
      return
    }

    if (!conv) {
      container.innerHTML = `
        <div class="h-full flex items-center justify-center p-8 text-sm text-slate-400">
          Выберите диалог из списка слева для просмотра
        </div>
      `
      return
    }

    const isCall =
      conv.channel.toLowerCase().includes('call') || conv.channel.toLowerCase().includes('voice')

    container.innerHTML = `
      <div class="h-full flex flex-col bg-white dark:bg-slate-900 overflow-hidden">
        <!-- Шапка диалога -->
        <div class="px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/70 flex flex-wrap items-center justify-between gap-3 shrink-0">
          <div class="flex items-center gap-3">
            <h2 class="text-lg font-bold tracking-tight text-slate-900 dark:text-white">
              ${escapeHtml(conv.id)}
            </h2>
            <span class="text-xs px-2.5 py-0.5 rounded-full font-semibold ${
              conv.language === 'RU'
                ? 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200'
                : conv.language === 'KZ'
                  ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200'
                  : 'bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-200'
            }">
              ${escapeHtml(conv.language)}
            </span>
            <span class="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-semibold bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
              <span class="material-symbols-outlined text-[14px]">${isCall ? 'call' : 'chat'}</span>
              <span>${isCall ? 'Звонок' : 'Чат'}</span>
            </span>
          </div>

          <div class="text-xs text-slate-400 font-medium">
            ${conv.transcript.length} реплик
          </div>
        </div>

        <!-- Аудиоплеер для звонков -->
        ${
          conv.audio_url
            ? `
          <div class="px-5 py-3 bg-amber-500/10 dark:bg-amber-500/5 border-b border-amber-200/50 dark:border-amber-900/30 flex items-center justify-between gap-4 shrink-0">
            <div class="flex items-center gap-2 shrink-0">
              <span class="material-symbols-outlined text-amber-700 dark:text-amber-300 text-lg">headphones</span>
              <span class="text-xs font-bold text-amber-900 dark:text-amber-200 whitespace-nowrap">Запись звонка:</span>
            </div>
            <div class="flex-1 max-w-xl flex items-center gap-3">
              <audio
                id="cqa-call-audio-player"
                controls
                preload="metadata"
                src="/api/conversations/${encodeURIComponent(conv.id)}/audio"
                class="h-8 w-full"
              ></audio>
            </div>
          </div>
        `
            : ''
        }

        <!-- Список реплик -->
        <div id="cqa-transcript-scroll" class="flex-1 overflow-y-auto p-4 sm:p-6 space-y-3.5">
          ${conv.transcript
            .map((u: Utterance, idx: number) => {
              const isOperator = u.speaker === 'operator'
              const isClient = u.speaker === 'client'
              const isBot = u.speaker === 'bot'
              const isHighlighted =
                state.highlightedIndex === idx ||
                (state.highlightedRange &&
                  idx >= state.highlightedRange.from &&
                  idx <= state.highlightedRange.to)

              return `
                <div
                  id="utterance-${idx}"
                  class="p-3.5 rounded-xl border transition-all ${
                    isHighlighted
                      ? 'ring-2 ring-emerald-500 bg-emerald-50/70 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-700 shadow-sm'
                      : isOperator
                        ? 'bg-emerald-50/30 dark:bg-emerald-950/10 border-emerald-100 dark:border-emerald-900/30'
                        : isClient
                          ? 'bg-blue-50/30 dark:bg-blue-950/10 border-blue-100 dark:border-blue-900/30'
                          : isBot
                            ? 'bg-amber-50/30 dark:bg-amber-950/10 border-amber-100 dark:border-amber-900/30'
                            : 'bg-slate-50 dark:bg-slate-800/40 border-slate-200 dark:border-slate-800'
                  }"
                >
                  <div class="flex items-center justify-between gap-3 text-xs mb-2">
                    <div class="flex items-center gap-2">
                      <span class="font-bold px-2 py-0.5 rounded text-xs uppercase tracking-wider ${
                        isOperator
                          ? 'bg-emerald-600 text-white'
                          : isClient
                            ? 'bg-blue-600 text-white'
                            : isBot
                              ? 'bg-amber-600 text-white'
                              : 'bg-slate-600 text-white'
                      }">
                        ${
                          isOperator
                            ? 'Оператор'
                            : isClient
                              ? 'Клиент'
                              : isBot
                                ? 'Бот'
                                : 'Система'
                        }
                      </span>
                      <span class="font-mono text-xs text-slate-400">
                        [#${idx} / turn ${idx + 1}]
                      </span>
                    </div>
                    <span
                      class="font-mono text-xs text-slate-400 font-medium whitespace-nowrap"
                      title="${escapeHtml(u.timestamp)}"
                    >
                      ${escapeHtml(formatTimestamp(u.timestamp))}
                    </span>
                  </div>

                  <div class="text-[14.5px] text-slate-800 dark:text-slate-100 leading-relaxed whitespace-pre-wrap font-normal">
                    ${escapeHtml(u.text)}
                  </div>
                </div>
              `
            })
            .join('')}
        </div>
      </div>
    `

    // Если есть подсветка, скроллим к ней
    if (state.highlightedIndex !== null) {
      setTimeout(() => {
        const target = container.querySelector(`#utterance-${state.highlightedIndex}`)
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
      }, 50)
    } else if (state.highlightedRange !== null) {
      setTimeout(() => {
        const target = container.querySelector(`#utterance-${state.highlightedRange?.from}`)
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
      }, 50)
    }
  })
}

