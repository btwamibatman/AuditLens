import { cqaApi } from '@/features/cqa/api'
import { escapeHtml, formatTimestamp } from '@/lib/dom'
import { store, type AppState } from '@/state/store'
import type { CriterionResult, Evidence } from '@/types/cqa'
import { showAppealCreateModal, showAppealReviewModal } from './AppealModal'

export function renderEvaluationCard(container: HTMLElement) {
  async function runEvaluation() {
    const state = store.getState()
    const convId = state.selectedConversationId
    if (!convId || state.evaluating) return

    store.setState({ evaluating: true, evalError: null })
    try {
      const res = await cqaApi.evaluate(convId, state.selectedChecklistId)
      store.setState({ currentEvaluation: res })
      store.showToast('success', 'Оценка диалога успешно завершена!')
      // Обновляем историю и апелляции
      const [history, allEvals, appeals, allAppeals] = await Promise.all([
        cqaApi.listEvaluations(convId),
        cqaApi.listEvaluations().catch(() => []),
        cqaApi.listAppeals(res.id).catch(() => []),
        cqaApi.listAppeals().catch(() => []),
      ])
      store.setState({
        evaluationHistory: history,
        allEvaluations: allEvals,
        appeals,
        allAppeals,
      })
    } catch (err: any) {
      store.setState({ evalError: err.message || 'Ошибка оценки диалога' })
      store.showToast('error', err.message || 'Ошибка оценки диалога')
    } finally {
      store.setState({ evaluating: false })
    }
  }

  async function loadHistoryEvaluation(id: number) {
    try {
      const ev = await cqaApi.getEvaluation(id)
      const appeals = await cqaApi.listAppeals(ev.id)
      store.setState({ currentEvaluation: ev, appeals })
    } catch (err: any) {
      store.showToast('error', err.message || 'Ошибка загрузки оценки из истории')
    }
  }

  store.subscribe((state: AppState) => {
    const ev = state.currentEvaluation
    const isMock = ev?.model ? ev.model.toLowerCase().includes('mock') : true
    const activeResult = ev?.final_result ?? ev?.ai_result
    const totalScore = ev?.total_score ?? activeResult?.total ?? null
    const hasCritical = ev?.has_critical_error ?? activeResult?.has_critical_error ?? false

    container.innerHTML = `
      <div class="h-full flex flex-col bg-white dark:bg-slate-900 overflow-hidden">
        <!-- Верхний тулбар оценки -->
        <div class="p-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 space-y-3 shrink-0">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-2.5 flex-1">
              <label class="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider whitespace-nowrap">
                Чек-лист:
              </label>
              <select
                id="cqa-checklist-select"
                class="text-xs py-2 px-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100 flex-1 min-w-0 w-full max-w-xs truncate focus:outline-none focus:ring-1 focus:ring-emerald-500 font-medium"
              >
                ${state.checklists
                  .map(
                    (cl) => `
                  <option value="${cl.id}" ${
                    (state.selectedChecklistId ?? state.activeChecklist?.id) === cl.id
                      ? 'selected'
                      : ''
                  }>
                    #${cl.id} ${escapeHtml(cl.name)} ${cl.is_active ? '(активный)' : ''}
                  </option>
                `,
                  )
                  .join('')}
              </select>
            </div>

            <button
              id="cqa-run-eval-btn"
              ${state.evaluating || !state.selectedConversationId ? 'disabled' : ''}
              class="px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition-colors shadow-xs"
            >
              ${state.evaluating ? 'Оценка выполняется...' : 'Оценить диалог'}
            </button>
          </div>

          <!-- История оценок диалога -->
          ${
            state.evaluationHistory.length > 1
              ? `
            <div class="flex items-center gap-2 text-xs text-slate-500">
              <span class="font-medium">История:</span>
              <select
                id="cqa-history-select"
                class="text-xs py-1 px-2 rounded border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 font-medium"
              >
                ${state.evaluationHistory
                  .map(
                    (h) => `
                  <option value="${h.id}" ${ev?.id === h.id ? 'selected' : ''}>
                    Оценка #${h.id} (${h.total_score ?? '—'} б.) [${h.created_at.slice(11, 16)}]
                  </option>
                `,
                  )
                  .join('')}
              </select>
            </div>
          `
              : ''
          }
        </div>

        <!-- Контент карточки -->
        <div class="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
          ${
            state.evaluating
              ? `
            <div class="p-8 text-center text-sm text-slate-400">
              <div class="text-3xl mb-2 text-emerald-500 animate-spin">
                <span class="material-symbols-outlined text-4xl">sync</span>
              </div>
              <div class="font-semibold text-slate-700 dark:text-slate-200 text-base">AI выполняет оценку диалога...</div>
              <div class="text-slate-400 mt-1 text-xs">Проверяются 8 критериев по официальному чек-листу CQA</div>
            </div>
          `
              : state.evalError
                ? `
            <div class="p-4 bg-red-50 text-red-700 rounded-xl border border-red-200 text-xs">
              <div class="font-bold mb-1">Ошибка при оценке:</div>
              <div>${escapeHtml(state.evalError)}</div>
            </div>
          `
                : !ev
                  ? `
            <div class="p-8 text-center text-sm text-slate-400">
              Диалог ещё не оценён. Нажмите «Оценить диалог», чтобы запустить проверку.
            </div>
          `
                  : `
            <!-- Итоговый результат -->
            <div class="p-5 rounded-2xl bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-800/80 dark:to-slate-900 border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-4">
              <div>
                <div class="text-xs font-bold uppercase tracking-wider text-slate-500">
                  Итоговое качество оператора
                </div>
                <div class="text-3xl font-black text-slate-900 dark:text-white mt-1">
                  ${totalScore !== null ? `${totalScore} / 100` : '—'}
                </div>
                <div class="flex items-center gap-2 mt-2.5">
                  <span class="inline-flex items-center gap-1 text-xs px-2.5 py-0.5 rounded-full font-semibold ${
                    ev.status === 'done'
                      ? 'bg-emerald-100 text-emerald-800'
                      : 'bg-amber-100 text-amber-800'
                  }">
                    ${ev.status === 'done' ? '<span class="material-symbols-outlined text-[13px]">check_circle</span><span>Оценка завершена</span>' : ev.status}
                  </span>
                  ${
                    isMock
                      ? `
                    <span class="text-xs font-bold px-2 py-0.5 rounded bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200">
                      MOCK
                    </span>
                  `
                      : ''
                  }
                  ${
                    hasCritical
                      ? `
                    <span class="text-xs font-bold px-2.5 py-0.5 rounded bg-red-600 text-white animate-pulse">
                      ГРУБАЯ ОШИБКА
                    </span>
                  `
                      : ''
                  }
                </div>
              </div>

              <!-- Круговой бейдж балла -->
              <div class="w-16 h-16 rounded-full flex items-center justify-center font-black text-xl ${
                totalScore !== null && totalScore >= 70
                  ? 'bg-emerald-500 text-white shadow-emerald-500/20 shadow-lg'
                  : totalScore !== null && totalScore >= 40
                    ? 'bg-amber-500 text-white shadow-amber-500/20 shadow-lg'
                    : 'bg-red-500 text-white shadow-red-500/20 shadow-lg'
              }">
                ${totalScore !== null ? `${Math.round(totalScore)}%` : '—'}
              </div>
            </div>

            <!-- Мета-информация о модели -->
            <div class="text-xs text-slate-400 flex flex-wrap items-center gap-3.5 px-1 font-medium">
              <span>Модель: <b class="text-slate-600 dark:text-slate-300 font-semibold">${escapeHtml(ev.model || 'mock')}</b></span>
              ${ev.latency_ms ? `<span>Время: <b>${(ev.latency_ms / 1000).toFixed(1)}с</b></span>` : ''}
              ${ev.cost_usd ? `<span>Стоимость: <b>$${ev.cost_usd.toFixed(4)}</b></span>` : ''}
              <span>Версия чек-листа: <b>v${ev.checklist_version}</b></span>
            </div>

            <!-- Список критериев -->
            <div class="space-y-3.5">
              <div class="text-xs font-extrabold text-slate-900 dark:text-white uppercase tracking-wider">
                Критерии оценки
              </div>

              ${
                activeResult?.criteria
                  .map((crit: CriterionResult) => {
                    const isNa = crit.status === 'na' || crit.score === null
                    const appealsForCrit = state.appeals.filter(
                      (a) => a.criterion_id === crit.criterion_id,
                    )

                    return `
                  <div class="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40 space-y-2.5">
                    <div class="flex items-start justify-between gap-2">
                      <div>
                        <div class="font-bold text-sm text-slate-900 dark:text-white">
                          ${escapeHtml(crit.name)}
                        </div>
                        <div class="text-xs text-slate-400 mt-0.5">
                          Вес: ${crit.weight} • Балл: ${crit.score ?? '—'} (вклад: ${crit.points?.toFixed(1) ?? '—'})
                        </div>
                      </div>

                      <div>
                        ${
                          isNa
                            ? `
                          <span class="text-xs font-bold px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
                            N/A
                          </span>
                        `
                            : crit.critical_violation
                              ? `
                          <span class="text-xs font-bold px-2 py-0.5 rounded bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300">
                            Грубая ошибка
                          </span>
                        `
                              : crit.score && crit.score > 0
                                ? `
                          <span class="inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                            <span class="material-symbols-outlined text-[13px]">check</span>
                            <span>Выполнено (${crit.score})</span>
                          </span>
                        `
                                : `
                          <span class="inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300">
                            <span class="material-symbols-outlined text-[13px]">close</span>
                            <span>Не выполнено (0)</span>
                          </span>
                        `
                        }
                      </div>
                    </div>

                    <!-- Обоснование -->
                    <div class="text-[13.5px] text-slate-700 dark:text-slate-200 leading-relaxed font-normal">
                      ${escapeHtml(crit.explanation)}
                    </div>

                    ${
                      isNa && crit.na_reason
                        ? `
                      <div class="text-xs text-slate-500 italic">
                        Причина N/A: ${escapeHtml(crit.na_reason)}
                      </div>
                    `
                        : ''
                    }

                    <!-- Доказательства: цитаты -->
                    ${
                      crit.evidence && crit.evidence.length > 0
                        ? `
                      <div class="space-y-2 pt-1">
                        ${crit.evidence
                          .map((evItem: Evidence) => {
                            return `
                            <div
                              data-evidence-index="${evItem.message_index}"
                              class="cqa-evidence-click group cursor-pointer p-3 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-xs hover:border-emerald-500 transition-colors shadow-2xs"
                            >
                              <div class="flex items-center justify-between gap-2.5 mb-1.5">
                                <div
                                  class="truncate text-xs text-emerald-600 dark:text-emerald-400 group-hover:underline font-medium"
                                  title="${escapeHtml(evItem.timestamp)}"
                                >
                                  Реплика [#${evItem.message_index} / turn ${evItem.message_index + 1}] • ${escapeHtml(evItem.speaker)} • <span class="font-mono text-slate-400 font-normal">${escapeHtml(formatTimestamp(evItem.timestamp))}</span>
                                </div>
                                <span class="shrink-0 text-[11px] px-2 py-0.5 rounded font-semibold whitespace-nowrap inline-flex items-center gap-1 ${
                                  evItem.verified
                                    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300'
                                    : 'bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300'
                                }">
                                  <span class="material-symbols-outlined text-[12px]">${evItem.verified ? 'verified' : 'warning'}</span>
                                  <span>${evItem.verified ? 'подтверждено' : 'цитата неточная'}</span>
                                </span>
                              </div>
                              <div class="font-medium text-[13.5px] text-slate-800 dark:text-slate-200 leading-normal">
                                «${escapeHtml(evItem.quote)}»
                              </div>
                            </div>
                          `
                          })
                          .join('')}
                      </div>
                    `
                        : ''
                    }

                    <!-- Проверенный диапазон для пропущенных действий -->
                    ${
                      crit.checked_range
                        ? `
                      <div
                        data-range-from="${crit.checked_range.from_index}"
                        data-range-to="${crit.checked_range.to_index}"
                        class="cqa-range-click cursor-pointer mt-2 rounded-lg p-2.5 bg-slate-100/70 dark:bg-slate-900/60 text-xs text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-800 flex items-center justify-between gap-2"
                      >
                        <span class="truncate" title="${escapeHtml(crit.checked_range.from_timestamp)} — ${escapeHtml(crit.checked_range.to_timestamp)}">
                          <span class="material-symbols-outlined text-[15px] align-middle mr-1 text-slate-500">manage_search</span>
                          <span>Проверенный диапазон: <b>[#${crit.checked_range.from_index} .. #${crit.checked_range.to_index}]</b></span>
                          <span class="text-slate-400">(${escapeHtml(formatTimestamp(crit.checked_range.from_timestamp))} — ${escapeHtml(formatTimestamp(crit.checked_range.to_timestamp))})</span>
                        </span>
                        <span class="shrink-0 text-emerald-600 dark:text-emerald-400 underline text-xs font-medium">Показать участок</span>
                      </div>
                    `
                        : ''
                    }

                    <!-- Блок апелляций -->
                    <div class="pt-2.5 border-t border-slate-200/60 dark:border-slate-700/40 flex flex-wrap items-center justify-between gap-2">
                      <div class="text-xs text-indigo-600 font-semibold">
                        ${appealsForCrit.length > 0 ? `Апелляций: ${appealsForCrit.length}` : ''}
                      </div>

                      <button
                        data-appeal-crit-id="${escapeHtml(crit.criterion_id)}"
                        class="cqa-open-appeal-btn text-xs font-semibold px-3 py-1 rounded text-indigo-600 hover:text-indigo-950 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-950/50 dark:hover:text-white border border-indigo-200 dark:border-indigo-800 transition-colors"
                      >
                        Оспорить оценку
                      </button>
                    </div>

                    <!-- Существующие апелляции по критерию -->
                    ${
                      appealsForCrit.length > 0
                        ? `
                      <div class="space-y-2 pt-1">
                        ${appealsForCrit
                          .map((app) => {
                            const isPending = app.status === 'pending'
                            return `
                            <div class="p-2.5 rounded-lg bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-100 dark:border-indigo-900/40 text-xs space-y-1">
                              <div class="flex items-center justify-between">
                                <span class="font-bold text-[10px] uppercase px-1.5 py-0.5 rounded ${
                                  isPending
                                    ? 'bg-amber-100 text-amber-800'
                                    : 'bg-emerald-100 text-emerald-800'
                                }">
                                  ${isPending ? 'На рассмотрении' : 'Пересмотрена'}
                                </span>
                                ${
                                  isPending
                                    ? `
                                  <button
                                    data-review-appeal-id="${app.id}"
                                    class="cqa-review-appeal-btn text-xs font-semibold text-emerald-600 hover:underline"
                                  >
                                    Рассмотреть (Проверяющий)
                                  </button>
                                `
                                    : ''
                                }
                              </div>
                              <div class="text-slate-600 dark:text-slate-300">
                                <b>Аргумент:</b> «${escapeHtml(app.comment)}»
                              </div>
                              ${
                                app.reviewer_comment
                                  ? `
                                <div class="text-emerald-700 dark:text-emerald-300 font-medium pt-1 border-t border-indigo-100 dark:border-indigo-900/40">
                                  Решение проверяющего: <b>${app.decision === 'change' ? 'Оценка изменена' : 'Подтверждена'}</b>
                                  — ${escapeHtml(app.reviewer_comment)}
                                </div>
                              `
                                  : ''
                              }
                            </div>
                          `
                          })
                          .join('')}
                      </div>
                    `
                        : ''
                    }
                  </div>
                `
                  })
                  .join('')
              }
            </div>
          `
          }
        </div>
      </div>
    `

    // Слушатели событий
    const checklistSelect = container.querySelector(
      '#cqa-checklist-select',
    ) as HTMLSelectElement | null
    checklistSelect?.addEventListener('change', () => {
      const val = parseInt(checklistSelect.value, 10)
      store.setState({ selectedChecklistId: isNaN(val) ? null : val })
    })

    const historySelect = container.querySelector(
      '#cqa-history-select',
    ) as HTMLSelectElement | null
    historySelect?.addEventListener('change', () => {
      const val = parseInt(historySelect.value, 10)
      if (!isNaN(val)) void loadHistoryEvaluation(val)
    })

    container.querySelector('#cqa-run-eval-btn')?.addEventListener('click', () => {
      void runEvaluation()
    })

    // Клик по доказательству: скролл к реплике
    container.querySelectorAll('.cqa-evidence-click').forEach((el) => {
      el.addEventListener('click', () => {
        const idx = parseInt(el.getAttribute('data-evidence-index') || '-1', 10)
        if (idx >= 0) {
          store.setState({ highlightedIndex: idx, highlightedRange: null })
        }
      })
    })

    // Клик по диапазону
    container.querySelectorAll('.cqa-range-click').forEach((el) => {
      el.addEventListener('click', () => {
        const from = parseInt(el.getAttribute('data-range-from') || '0', 10)
        const to = parseInt(el.getAttribute('data-range-to') || '0', 10)
        store.setState({ highlightedRange: { from, to }, highlightedIndex: null })
      })
    })

    // Открытие формы подачи апелляции
    container.querySelectorAll('.cqa-open-appeal-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const critId = btn.getAttribute('data-appeal-crit-id')
        const crit = activeResult?.criteria.find((c: CriterionResult) => c.criterion_id === critId)
        if (crit && ev) {
          showAppealCreateModal(crit, ev.id)
        }
      })
    })

    // Открытие окна рассмотрения проверяющим
    container.querySelectorAll('.cqa-review-appeal-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const appealId = parseInt(btn.getAttribute('data-review-appeal-id') || '-1', 10)
        const appeal = state.appeals.find((a) => a.id === appealId)
        if (appeal && ev) {
          showAppealReviewModal(appeal, ev)
        }
      })
    })
  })
}
