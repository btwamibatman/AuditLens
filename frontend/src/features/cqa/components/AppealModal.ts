import { cqaApi } from '@/features/cqa/api'
import { escapeHtml } from '@/lib/dom'
import { store } from '@/state/store'
import type { AppealCreate, AppealRead, AppealReview, CriterionResult, EvaluationRead } from '@/types/cqa'

export function showAppealCreateModal(criterion: CriterionResult, evaluationId: number) {
  const existing = document.getElementById('cqa-appeal-create-modal')
  if (existing) existing.remove()

  const modalHtml = `
    <div id="cqa-appeal-create-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
      <div class="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 max-w-md w-full p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-base font-bold text-slate-900 dark:text-white">
            Подача апелляции
          </h3>
          <button id="modal-close-btn" class="text-slate-400 hover:text-slate-600 text-xl font-bold">&times;</button>
        </div>

        <div class="text-sm text-slate-600 dark:text-slate-300">
          Критерий: <span class="font-bold text-slate-900 dark:text-white">${escapeHtml(criterion.name)}</span>
        </div>

        <div>
          <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1.5 uppercase tracking-wider">
            Комментарий оператора:
          </label>
          <textarea
            id="appeal-comment-input"
            rows="3"
            placeholder="Укажите, с чем вы не согласны, и приведите аргументы оператора..."
            class="w-full text-sm p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-normal leading-relaxed"
          ></textarea>
          <div id="appeal-modal-error" class="text-xs text-red-600 mt-1 hidden font-semibold"></div>
        </div>

        <div class="flex items-center justify-end gap-2.5 pt-2">
          <button
            id="modal-cancel-btn"
            class="px-3.5 py-2 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white transition-colors"
          >
            Отмена
          </button>
          <button
            id="modal-submit-btn"
            class="px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider bg-indigo-600 text-white hover:bg-indigo-700"
          >
            Отправить обращение
          </button>
        </div>
      </div>
    </div>
  `

  document.body.insertAdjacentHTML('beforeend', modalHtml)
  const modal = document.getElementById('cqa-appeal-create-modal')!
  const textarea = modal.querySelector('#appeal-comment-input') as HTMLTextAreaElement
  const errorEl = modal.querySelector('#appeal-modal-error') as HTMLElement
  const submitBtn = modal.querySelector('#modal-submit-btn') as HTMLButtonElement

  function close() {
    modal.remove()
  }

  modal.querySelector('#modal-close-btn')?.addEventListener('click', close)
  modal.querySelector('#modal-cancel-btn')?.addEventListener('click', close)

  submitBtn.addEventListener('click', async () => {
    const comment = textarea.value.trim()
    if (!comment) {
      errorEl.textContent = 'Комментарий не может быть пустым'
      errorEl.classList.remove('hidden')
      return
    }
    submitBtn.disabled = true
    submitBtn.textContent = 'Отправка...'
    try {
      const payload: AppealCreate = {
        evaluation_id: evaluationId,
        criterion_id: criterion.criterion_id,
        comment,
      }
      await cqaApi.createAppeal(payload)
      store.showToast('success', 'Апелляция успешно создана и отправлена на рассмотрение!')
      close()
      // Перечитываем апелляции
      const [appeals, allAppeals] = await Promise.all([
        cqaApi.listAppeals(evaluationId).catch(() => []),
        cqaApi.listAppeals().catch(() => []),
      ])
      store.setState({ appeals, allAppeals })
    } catch (err: any) {
      errorEl.textContent = err.message || 'Ошибка отправки апелляции'
      errorEl.classList.remove('hidden')
      submitBtn.disabled = false
      submitBtn.textContent = 'Отправить обращение'
    }
  })
}

export function showAppealReviewModal(appeal: AppealRead, evaluation: EvaluationRead) {
  const existing = document.getElementById('cqa-appeal-review-modal')
  if (existing) existing.remove()

  const activeResult = evaluation.final_result ?? evaluation.ai_result
  const crit = activeResult?.criteria.find((c: CriterionResult) => c.criterion_id === appeal.criterion_id)
  const snapshotConfig =
    evaluation.checklist_snapshot ??
    store.getState().checklists.find((c) => c.id === evaluation.checklist_id)?.config ??
    store.getState().activeChecklist?.config
  const rule = snapshotConfig?.criteria.find((c) => c.id === appeal.criterion_id)

  const isCritical = Boolean(crit?.is_critical || rule?.is_critical || appeal.criterion_id === 'critical')
  const naAllowed = Boolean(rule ? rule.na_allowed : ['discovery', 'identification', 'consultation', 'closure'].includes(appeal.criterion_id))
  const answerType = rule?.answer_type || crit?.answer_type || 'binary'

  // Формируем допустимые варианты оценки строго по снимку чек-листа
  const options: { value: string; label: string; selected: boolean }[] = []
  const currentIsNa = crit?.status === 'na' || crit?.score === null
  const currentScore = crit?.score

  if (answerType === 'scale' && rule?.scale_levels?.length) {
    for (const lvl of rule.scale_levels) {
      options.push({
        value: String(lvl.value),
        label: `${lvl.value} б. — ${lvl.description}`,
        selected: !currentIsNa && currentScore === lvl.value,
      })
    }
  } else if (answerType === 'scale') {
    const steps = appeal.criterion_id === 'dialogue' ? [10, 7, 4, 0] : [20, 15, 10, 5, 0]
    for (const val of steps) {
      options.push({
        value: String(val),
        label: `${val} баллов`,
        selected: !currentIsNa && currentScore === val,
      })
    }
  } else if (isCritical) {
    options.push(
      {
        value: '0',
        label: '0 — Грубых ошибок нет (Нет)',
        selected: !currentIsNa && currentScore === 0,
      },
      {
        value: '1',
        label: '1 — Выявлена грубая ошибка (Да)',
        selected: !currentIsNa && currentScore === 1,
      },
    )
  } else {
    options.push(
      {
        value: '1',
        label: '1 — Выполнено (Да)',
        selected: !currentIsNa && currentScore === 1,
      },
      {
        value: '0',
        label: '0 — Не выполнено (Нет)',
        selected: !currentIsNa && currentScore === 0,
      },
    )
  }

  if (naAllowed) {
    options.push({
      value: 'na',
      label: 'N/A — Неприменимо (исключить критерий и перераспределить вес)',
      selected: currentIsNa,
    })
  }

  const modalHtml = `
    <div id="cqa-appeal-review-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4">
      <div class="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 max-w-lg w-full p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-base font-bold text-slate-900 dark:text-white">
            Решение проверяющего по апелляции #${appeal.id}
          </h3>
          <button id="modal-review-close-btn" class="text-slate-400 hover:text-slate-600 text-xl font-bold">&times;</button>
        </div>

        <div class="p-3.5 bg-slate-50 dark:bg-slate-800/60 rounded-xl text-sm space-y-1.5 leading-relaxed">
          <div><b>Критерий:</b> ${escapeHtml(crit?.name || appeal.criterion_id)}</div>
          <div><b>Текущая оценка:</b> ${currentIsNa ? 'N/A (неприменимо)' : `${crit?.score ?? '—'} б.`}</div>
          <div><b>Аргумент оператора:</b> «${escapeHtml(appeal.comment)}»</div>
        </div>

        <!-- Выбор решения -->
        <div class="space-y-2">
          <label class="block text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
            Решение проверяющего:
          </label>
          <div class="flex items-center gap-5 text-sm">
            <label class="flex items-center gap-2 cursor-pointer font-medium">
              <input type="radio" name="review-decision" value="confirm" checked />
              <span>Подтвердить оценку AI</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer font-medium">
              <input type="radio" name="review-decision" value="change" />
              <span>Изменить оценку</span>
            </label>
          </div>
        </div>

        <!-- Поля при change -->
        <div id="review-change-fields" class="space-y-3 pt-2.5 border-t border-slate-100 dark:border-slate-800 hidden">
          <div>
            <label class="block font-semibold mb-1.5 text-xs uppercase tracking-wider text-slate-700 dark:text-slate-300">
              Новое значение критерия:
            </label>
            <select
              id="review-value-select"
              class="w-full p-2.5 border rounded-lg bg-white dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-100 text-sm font-medium"
            >
              ${options
                .map(
                  (opt) =>
                    `<option value="${escapeHtml(opt.value)}" ${opt.selected ? 'selected' : ''}>${escapeHtml(opt.label)}</option>`,
                )
                .join('')}
            </select>
          </div>
        </div>

        <!-- Обязательная причина -->
        <div>
          <label class="block text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
            Причина решения (обязательно):
          </label>
          <textarea
            id="review-reason-input"
            rows="2"
            placeholder="Опишите причину подтверждения или изменения оценки..."
            class="w-full text-sm p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-emerald-500 font-normal leading-relaxed"
          ></textarea>
          <div id="review-modal-error" class="text-xs text-red-600 mt-1 hidden font-semibold"></div>
        </div>

        <div class="flex items-center justify-end gap-2.5 pt-2">
          <button
            id="modal-review-cancel-btn"
            class="px-3.5 py-2 rounded-lg text-xs font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white transition-colors"
          >
            Отмена
          </button>
          <button
            id="modal-review-submit-btn"
            class="px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider bg-emerald-600 text-white hover:bg-emerald-700"
          >
            Зафиксировать решение
          </button>
        </div>
      </div>
    </div>
  `

  document.body.insertAdjacentHTML('beforeend', modalHtml)
  const modal = document.getElementById('cqa-appeal-review-modal')!
  const changeFields = modal.querySelector('#review-change-fields') as HTMLElement
  const reasonInput = modal.querySelector('#review-reason-input') as HTMLTextAreaElement
  const errorEl = modal.querySelector('#review-modal-error') as HTMLElement
  const submitBtn = modal.querySelector('#modal-review-submit-btn') as HTMLButtonElement

  function close() {
    modal.remove()
  }

  modal.querySelector('#modal-review-close-btn')?.addEventListener('click', close)
  modal.querySelector('#modal-review-cancel-btn')?.addEventListener('click', close)

  modal.querySelectorAll('input[name="review-decision"]').forEach((radio) => {
    radio.addEventListener('change', (e) => {
      const val = (e.target as HTMLInputElement).value
      if (val === 'change') {
        changeFields.classList.remove('hidden')
      } else {
        changeFields.classList.add('hidden')
      }
    })
  })

  submitBtn.addEventListener('click', async () => {
    const decision = (
      modal.querySelector('input[name="review-decision"]:checked') as HTMLInputElement
    ).value as 'confirm' | 'change'
    const reason = reasonInput.value.trim()

    if (!reason) {
      errorEl.textContent = 'Причина решения обязательна'
      errorEl.classList.remove('hidden')
      return
    }

    const payload: AppealReview = {
      decision,
      reviewer_comment: reason,
    }

    if (decision === 'change') {
      const selectedVal = (modal.querySelector('#review-value-select') as HTMLSelectElement).value
      if (selectedVal === 'na') {
        payload.new_is_na = true
        payload.new_score = null
        payload.new_critical_violation = false
        payload.new_na_reason = reason
      } else {
        const scoreVal = parseFloat(selectedVal)
        payload.new_is_na = false
        payload.new_score = isNaN(scoreVal) ? undefined : scoreVal
        payload.new_critical_violation = isCritical ? scoreVal > 0 : false
      }
    }

    submitBtn.disabled = true
    submitBtn.textContent = 'Сохранение...'

    try {
      // Endpoint /appeals/{id}/review возвращает пересчитанный EvaluationRead
      const updatedEval = await cqaApi.reviewAppeal(appeal.id, payload)
      store.showToast('success', 'Решение зафиксировано, оценка пересчитана!')
      close()
      store.setState({ currentEvaluation: updatedEval })
      const [appeals, allEvals, allAppeals] = await Promise.all([
        cqaApi.listAppeals(updatedEval.id).catch(() => []),
        cqaApi.listEvaluations().catch(() => []),
        cqaApi.listAppeals().catch(() => []),
      ])
      store.setState({ appeals, allEvaluations: allEvals, allAppeals })
    } catch (err: any) {
      errorEl.textContent = err.message || 'Ошибка сохранения решения'
      errorEl.classList.remove('hidden')
      submitBtn.disabled = false
      submitBtn.textContent = 'Зафиксировать решение'
    }
  })
}
