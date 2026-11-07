import { cqaApi } from '@/features/cqa/api'
import { escapeHtml } from '@/lib/dom'
import { store } from '@/state/store'
import type { ChecklistConfig, ChecklistRead, Criterion } from '@/types/cqa'

export function renderChecklistEditor(container: HTMLElement) {
  let selectedChecklist: ChecklistRead | null = null
  let editingName = ''
  let editingDescription = ''
  let editingConfig: ChecklistConfig | null = null
  let saving = false
  let successMsg: string | null = null
  let errorMsg: string | null = null

  async function loadChecklists() {
    try {
      const list = await cqaApi.listChecklists()
      store.setState({ checklists: list })
      if (!selectedChecklist && list.length > 0) {
        const active = list.find((c) => c.is_active) || list[0]
        selectChecklist(active)
      } else if (selectedChecklist) {
        const refreshed = list.find((c) => c.id === selectedChecklist?.id)
        if (refreshed) {
          selectedChecklist = refreshed
        }
      }
      render()
    } catch (err: any) {
      errorMsg = err.message || 'Ошибка загрузки чек-листов'
      render()
    }
  }

  function selectChecklist(cl: ChecklistRead, preserveMessages = false) {
    selectedChecklist = cl
    editingName = cl.name
    editingDescription = cl.description || ''
    editingConfig = JSON.parse(JSON.stringify(cl.config))
    if (!preserveMessages) {
      successMsg = null
      errorMsg = null
    }
    render()
  }

  async function activateCurrent() {
    if (!selectedChecklist) return
    saving = true
    errorMsg = null
    render()
    try {
      await cqaApi.activateChecklist(selectedChecklist.id)
      store.showToast('success', `Чек-лист #${selectedChecklist.id} активирован!`)
      await loadChecklists()
    } catch (err: any) {
      errorMsg = err.message || 'Ошибка активации чек-листа'
    } finally {
      saving = false
      render()
    }
  }

  async function resetToDefault() {
    if (!confirm('Сбросить текущий чек-лист к базовой официальной конфигурации ТЗ (8 критериев)?')) return
    errorMsg = null
    try {
      const def = await cqaApi.getDefaultConfig()
      editingConfig = JSON.parse(JSON.stringify(def))
      editingName = 'Базовый чек-лист поддержки (ТЗ)'
      successMsg = 'Загружен шаблон из ТЗ. Нажмите «Сохранить конфигурацию», чтобы применить изменения.'
      render()
    } catch (err: any) {
      errorMsg = err.message || 'Ошибка загрузки базового шаблона'
      render()
    }
  }

  async function createNewChecklist() {
    saving = true
    errorMsg = null
    render()
    try {
      const def = await cqaApi.getDefaultConfig()
      const created = await cqaApi.createChecklist({
        name: `Новый чек-лист #${store.getState().checklists.length + 1}`,
        description: 'Пользовательский чек-лист качества',
        config: def,
      })
      await loadChecklists()
      selectChecklist(created)
      successMsg = `Создан новый чек-лист #${created.id}`
      store.showToast('success', `Создан чек-лист #${created.id}`)
    } catch (err: any) {
      errorMsg = err.message || 'Ошибка создания чек-листа'
    } finally {
      saving = false
      render()
    }
  }

  function addCriterion() {
    if (!editingConfig) return
    const newId = `criterion_${Date.now().toString(36).slice(-4)}`
    const newCriterion: Criterion = {
      id: newId,
      name: 'Новый критерий',
      section: 'Общие требования',
      description: 'Описание проверки поведения оператора',
      weight: 10,
      answer_type: 'binary',
      scale_min: 0,
      scale_max: 1,
      scale_levels: [],
      na_allowed: false,
      na_rule: '',
      is_critical: false,
      critical_rule: '',
      channels: ['chat', 'call'],
      enabled: true,
    }
    editingConfig.criteria.push(newCriterion)
    render()
  }

  function removeCriterion(idx: number) {
    if (!editingConfig) return
    editingConfig.criteria.splice(idx, 1)
    render()
  }

  function addScaleLevel(crit: Criterion) {
    const maxVal = crit.scale_levels.length > 0 ? Math.max(...crit.scale_levels.map((l) => l.value)) + 5 : 0
    crit.scale_levels.push({ value: maxVal, description: `Ступень ${maxVal}` })
    crit.scale_max = Math.max(crit.scale_max, maxVal)
    render()
  }

  function removeScaleLevel(crit: Criterion, levelIdx: number) {
    crit.scale_levels.splice(levelIdx, 1)
    render()
  }

  async function saveChanges() {
    if (!selectedChecklist || !editingConfig) return
    saving = true
    errorMsg = null
    successMsg = null
    render()

    // Валидация на клиенте
    const ids = editingConfig.criteria.map((c) => c.id.trim())
    if (new Set(ids).size !== ids.length) {
      errorMsg = 'Идентификаторы критериев (ID) должны быть уникальными!'
      saving = false
      render()
      return
    }

    for (const c of editingConfig.criteria) {
      if (!c.id.match(/^[a-z0-9_]{2,40}$/)) {
        errorMsg = `ID критерия «${c.name}» (${c.id}) должен состоять из строчных латинских букв, цифр и _ (2–40 символов).`
        saving = false
        render()
        return
      }
      if (c.weight < 0) {
        errorMsg = `Вес критерия «${c.name}» не может быть отрицательным.`
        saving = false
        render()
        return
      }
      if (c.na_allowed && !c.na_rule?.trim()) {
        errorMsg = `Для критерия «${c.name}» включен N/A, поэтому поле «Правило N/A» обязательно.`
        saving = false
        render()
        return
      }
      if (c.is_critical && !c.critical_rule?.trim()) {
        errorMsg = `Для критерия «${c.name}» включен флаг грубой ошибки, поэтому поле «Правило ошибки» обязательно.`
        saving = false
        render()
        return
      }
    }

    try {
      const updated = await cqaApi.updateChecklist(selectedChecklist.id, {
        name: editingName.trim(),
        description: editingDescription.trim(),
        config: editingConfig,
      })
      const msg = `Чек-лист #${updated.id} успешно сохранён! Новая версия: v${updated.version}.`
      successMsg = msg
      await loadChecklists()
      selectChecklist(updated, true)
      successMsg = msg
      store.showToast('success', msg)
    } catch (err: any) {
      errorMsg = err.message || 'Ошибка при сохранении чек-листа'
    } finally {
      saving = false
      render()
    }
  }

  function render() {
    const checklists = store.getState().checklists

    container.innerHTML = `
      <div class="h-full flex flex-col md:flex-row bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xs overflow-hidden">
        <!-- Боковая панель списка чек-листов -->
        <div class="w-full md:w-80 border-b md:border-b-0 md:border-r border-slate-200 dark:border-slate-800 flex flex-col bg-slate-50/50 dark:bg-slate-900/50 shrink-0">
          <div class="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <h2 class="text-sm font-semibold text-slate-900 dark:text-white">Конфигурации</h2>
            <button
              id="cqa-create-cl-btn"
              class="text-xs px-2.5 py-1 rounded bg-emerald-600 text-white font-medium hover:bg-emerald-700"
            >
              + Создать
            </button>
          </div>

          <div class="flex-1 overflow-y-auto p-3 space-y-2">
            ${checklists
              .map((cl) => {
                const isSelected = cl.id === selectedChecklist?.id
                return `
                  <div
                    data-cl-id="${cl.id}"
                    class="cqa-cl-item p-3 rounded-lg border text-xs cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-emerald-50/80 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-700 shadow-xs'
                        : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-300'
                    }"
                  >
                    <div class="flex items-center justify-between mb-1">
                      <span class="font-bold text-slate-800 dark:text-slate-100 truncate">
                        #${cl.id} ${escapeHtml(cl.name)}
                      </span>
                      ${
                        cl.is_active
                          ? `
                        <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300">
                          Активный
                        </span>
                      `
                          : ''
                      }
                    </div>
                    <div class="text-[11px] text-slate-400">
                      Версия v${cl.version} • ${cl.config?.criteria?.length || 0} критериев
                    </div>
                  </div>
                `
              })
              .join('')}
          </div>
        </div>

        <!-- Редактор выбранного чек-листа -->
        ${
          selectedChecklist && editingConfig
            ? `
          <div class="flex-1 flex flex-col overflow-hidden">
            <!-- Верхний тулбар действий -->
            <div class="p-4 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-wrap items-center justify-between gap-3">
              <div class="flex items-center gap-2">
                <span class="text-sm font-bold text-slate-900 dark:text-white">
                  Редактирование: #${selectedChecklist.id} (v${selectedChecklist.version})
                </span>
                ${
                  selectedChecklist.is_active
                    ? `
                  <span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">
                    Активная конфигурация
                  </span>
                `
                    : ''
                }
              </div>

              <div class="flex items-center gap-2">
                ${
                  !selectedChecklist.is_active
                    ? `
                  <button
                    id="cqa-activate-btn"
                    ${saving ? 'disabled' : ''}
                    class="px-3 py-1.5 rounded-lg text-xs font-medium border border-emerald-600 text-emerald-600 hover:bg-emerald-50 hover:text-emerald-950 transition-colors"
                  >
                    Сделать активным
                  </button>
                `
                    : ''
                }
                <button
                  id="cqa-reset-default-btn"
                  ${saving ? 'disabled' : ''}
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-300 text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors"
                >
                  Сброс к ТЗ
                </button>
                <button
                  id="cqa-save-cl-btn"
                  ${saving ? 'disabled' : ''}
                  class="px-4 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  ${saving ? 'Сохранение...' : 'Сохранить конфигурацию'}
                </button>
              </div>
            </div>

            <!-- Уведомления об успехе или ошибке -->
            ${
              successMsg
                ? `
              <div class="px-4 py-2.5 bg-emerald-50 text-xs text-emerald-700 border-b border-emerald-200">
                ${escapeHtml(successMsg)}
              </div>
            `
                : ''
            }
            ${
              errorMsg
                ? `
              <div class="px-4 py-2.5 bg-red-50 text-xs text-red-700 border-b border-red-200">
                ${escapeHtml(errorMsg)}
              </div>
            `
                : ''
            }

            <!-- Поля редактора -->
            <div class="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Название чек-листа:
                  </label>
                  <input
                    id="cl-name-input"
                    type="text"
                    value="${escapeHtml(editingName)}"
                    class="w-full text-sm p-2.5 border rounded-lg bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-700 font-medium"
                  />
                </div>
                <div>
                  <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">
                    Описание:
                  </label>
                  <input
                    id="cl-desc-input"
                    type="text"
                    value="${escapeHtml(editingDescription)}"
                    class="w-full text-sm p-2.5 border rounded-lg bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-700 font-medium"
                  />
                </div>
              </div>

              <div>
                <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">
                  Контекст компании и инструкции для модели (evaluator_notes):
                </label>
                <textarea
                  id="cl-notes-input"
                  rows="3"
                  class="w-full text-sm p-2.5 border rounded-lg bg-white dark:bg-slate-800 border-slate-300 dark:border-slate-700 font-normal leading-relaxed"
                >${escapeHtml(editingConfig.evaluator_notes || '')}</textarea>
              </div>

              <!-- Список критериев -->
              <div>
                <div class="flex items-center justify-between mb-4">
                  <h3 class="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white">
                    Критерии оценки (${editingConfig.criteria.length})
                  </h3>
                  <button
                    id="cqa-add-crit-btn"
                    class="text-xs px-3 py-1.5 rounded-lg border border-emerald-600 text-emerald-600 font-medium hover:bg-emerald-50 hover:text-emerald-950 transition-colors"
                  >
                    + Добавить критерий
                  </button>
                </div>

                <div class="space-y-4">
                  ${editingConfig.criteria
                    .map((crit, idx) => {
                      return `
                    <div class="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40 space-y-3">
                      <div class="flex items-center justify-between gap-3">
                        <div class="flex items-center gap-2">
                          <span class="font-mono text-xs font-bold text-slate-400">#${idx + 1}</span>
                          <input
                            data-crit-idx="${idx}"
                            data-field="name"
                            type="text"
                            placeholder="Название критерия"
                            value="${escapeHtml(crit.name)}"
                            class="crit-field text-sm font-semibold p-1.5 border rounded bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700"
                          />
                          <input
                            data-crit-idx="${idx}"
                            data-field="id"
                            type="text"
                            placeholder="Машинный ID (латиница)"
                            value="${escapeHtml(crit.id)}"
                            class="crit-field font-mono text-xs p-1.5 border rounded bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 w-32"
                          />
                        </div>
                        <button
                          data-del-crit="${idx}"
                          class="del-crit-btn text-xs text-red-600 hover:text-red-700 inline-flex items-center gap-0.5 font-medium"
                        >
                          <span class="material-symbols-outlined text-[14px]">delete</span>
                          <span>Удалить</span>
                        </button>
                      </div>

                      <div>
                        <label class="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1">Что проверяем:</label>
                        <textarea
                          data-crit-idx="${idx}"
                          data-field="description"
                          rows="2"
                          class="crit-field w-full text-sm p-2.5 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 font-normal leading-relaxed"
                        >${escapeHtml(crit.description)}</textarea>
                      </div>

                      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                        <div>
                          <label class="block font-semibold text-slate-600 dark:text-slate-300 mb-1">Вес критерия:</label>
                          <input
                            data-crit-idx="${idx}"
                            data-field="weight"
                            type="number"
                            value="${crit.weight}"
                            class="crit-field w-full text-sm p-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 font-medium"
                          />
                        </div>
                        <div>
                          <label class="block font-semibold text-slate-600 dark:text-slate-300 mb-1">Тип ответа:</label>
                          <select
                            data-crit-idx="${idx}"
                            data-field="answer_type"
                            class="crit-field w-full text-sm p-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 font-medium"
                          >
                            <option value="binary" ${crit.answer_type === 'binary' ? 'selected' : ''}>Бинарный (0 или 1)</option>
                            <option value="scale" ${crit.answer_type === 'scale' ? 'selected' : ''}>Шкала (дискретные уровни)</option>
                          </select>
                        </div>
                        <div>
                          <label class="block font-semibold text-slate-600 dark:text-slate-300 mb-1">Секция:</label>
                          <input
                            data-crit-idx="${idx}"
                            data-field="section"
                            type="text"
                            value="${escapeHtml(crit.section || '')}"
                            placeholder="Например: Начало разговора"
                            class="crit-field w-full text-sm p-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 font-medium"
                          />
                        </div>
                      </div>

                      <!-- Ступени шкалы -->
                      ${
                        crit.answer_type === 'scale'
                          ? `
                        <div class="p-3 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700 text-xs space-y-2">
                          <div class="flex items-center justify-between">
                            <span class="font-semibold">Ступени шкалы (макс. ${crit.scale_max}):</span>
                            <button
                              data-add-scale="${idx}"
                              class="add-scale-btn text-xs text-emerald-600 hover:underline"
                            >
                              + Добавить ступень
                            </button>
                          </div>
                          <div class="space-y-1.5">
                            ${crit.scale_levels
                              .map((lvl, lIdx) => {
                                return `
                              <div class="flex items-center gap-2">
                                <input
                                  data-crit-idx="${idx}"
                                  data-scale-idx="${lIdx}"
                                  data-scale-field="value"
                                  type="number"
                                  value="${lvl.value}"
                                  class="scale-field w-16 p-1 border rounded text-xs"
                                />
                                <input
                                  data-crit-idx="${idx}"
                                  data-scale-idx="${lIdx}"
                                  data-scale-field="description"
                                  type="text"
                                  value="${escapeHtml(lvl.description)}"
                                  placeholder="Описание уровня"
                                  class="scale-field flex-1 p-1 border rounded text-xs"
                                />
                                <button
                                  data-del-scale="${idx}:${lIdx}"
                                  class="del-scale-btn text-xs text-red-500 hover:text-red-700 inline-flex items-center justify-center p-0.5"
                                  title="Удалить ступень"
                                >
                                  <span class="material-symbols-outlined text-[14px]">close</span>
                                </button>
                              </div>
                            `
                              })
                              .join('')}
                          </div>
                        </div>
                      `
                          : ''
                      }

                      <!-- Правила N/A и критических ошибок -->
                      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-200/50 dark:border-slate-700/50 text-xs">
                        <div>
                          <label class="flex items-center gap-1.5 font-medium mb-1 cursor-pointer">
                            <input
                              data-crit-idx="${idx}"
                              data-field="na_allowed"
                              type="checkbox"
                              ${crit.na_allowed ? 'checked' : ''}
                              class="crit-checkbox rounded"
                            />
                            <span>Разрешён статус N/A</span>
                          </label>
                          ${
                            crit.na_allowed
                              ? `
                            <input
                              data-crit-idx="${idx}"
                              data-field="na_rule"
                              type="text"
                              value="${escapeHtml(crit.na_rule || '')}"
                              placeholder="Условие, когда критерий N/A"
                              class="crit-field w-full p-1.5 border rounded bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-xs mt-1"
                            />
                          `
                              : ''
                          }
                        </div>

                        <div>
                          <label class="flex items-center gap-1.5 font-medium mb-1 cursor-pointer">
                            <input
                              data-crit-idx="${idx}"
                              data-field="is_critical"
                              type="checkbox"
                              ${crit.is_critical ? 'checked' : ''}
                              class="crit-checkbox rounded"
                            />
                            <span>Грубая ошибка (critical)</span>
                          </label>
                          ${
                            crit.is_critical
                              ? `
                            <input
                              data-crit-idx="${idx}"
                              data-field="critical_rule"
                              type="text"
                              value="${escapeHtml(crit.critical_rule || '')}"
                              placeholder="Описание критического нарушения"
                              class="crit-field w-full p-1.5 border rounded bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-xs mt-1"
                            />
                          `
                              : ''
                          }
                        </div>
                      </div>
                    </div>
                  `
                    })
                    .join('')}
                </div>
              </div>
            </div>
          </div>
        `
            : `
          <div class="flex-1 flex items-center justify-center p-8 text-xs text-slate-400">
            Выберите конфигурацию слева для редактирования
          </div>
        `
        }
      </div>
    `

    // Слушатели событий
    container.querySelector('#cqa-create-cl-btn')?.addEventListener('click', createNewChecklist)
    container.querySelector('#cqa-activate-btn')?.addEventListener('click', activateCurrent)
    container.querySelector('#cqa-reset-default-btn')?.addEventListener('click', resetToDefault)
    container.querySelector('#cqa-save-cl-btn')?.addEventListener('click', saveChanges)
    container.querySelector('#cqa-add-crit-btn')?.addEventListener('click', addCriterion)

    const nameInput = container.querySelector('#cl-name-input') as HTMLInputElement | null
    nameInput?.addEventListener('input', () => {
      editingName = nameInput.value
    })

    const descInput = container.querySelector('#cl-desc-input') as HTMLInputElement | null
    descInput?.addEventListener('input', () => {
      editingDescription = descInput.value
    })

    const notesInput = container.querySelector('#cl-notes-input') as HTMLTextAreaElement | null
    notesInput?.addEventListener('input', () => {
      if (editingConfig) editingConfig.evaluator_notes = notesInput.value
    })

    container.querySelectorAll('.cqa-cl-item').forEach((item) => {
      item.addEventListener('click', () => {
        const id = parseInt(item.getAttribute('data-cl-id') || '-1', 10)
        const found = store.getState().checklists.find((c) => c.id === id)
        if (found) selectChecklist(found)
      })
    })

    container.querySelectorAll('.del-crit-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.getAttribute('data-del-crit') || '-1', 10)
        if (idx >= 0) removeCriterion(idx)
      })
    })

    container.querySelectorAll('.crit-field').forEach((el) => {
      el.addEventListener('change', (e) => {
        const target = e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
        const idx = parseInt(target.getAttribute('data-crit-idx') || '-1', 10)
        const field = target.getAttribute('data-field') as keyof Criterion
        if (idx >= 0 && editingConfig && field) {
          if (field === 'weight') {
            editingConfig.criteria[idx].weight = parseFloat(target.value) || 0
          } else {
            ;(editingConfig.criteria[idx] as any)[field] = target.value
          }
          if (field === 'answer_type') {
            render()
          }
        }
      })
    })

    container.querySelectorAll('.crit-checkbox').forEach((el) => {
      el.addEventListener('change', (e) => {
        const target = e.target as HTMLInputElement
        const idx = parseInt(target.getAttribute('data-crit-idx') || '-1', 10)
        const field = target.getAttribute('data-field') as keyof Criterion
        if (idx >= 0 && editingConfig && field) {
          ;(editingConfig.criteria[idx] as any)[field] = target.checked
          render()
        }
      })
    })

    container.querySelectorAll('.add-scale-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.getAttribute('data-add-scale') || '-1', 10)
        if (idx >= 0 && editingConfig) {
          addScaleLevel(editingConfig.criteria[idx])
        }
      })
    })

    container.querySelectorAll('.del-scale-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const [cIdx, sIdx] = (btn.getAttribute('data-del-scale') || '').split(':').map(Number)
        if (cIdx >= 0 && sIdx >= 0 && editingConfig) {
          removeScaleLevel(editingConfig.criteria[cIdx], sIdx)
        }
      })
    })

    container.querySelectorAll('.scale-field').forEach((el) => {
      el.addEventListener('change', (e) => {
        const target = e.target as HTMLInputElement
        const cIdx = parseInt(target.getAttribute('data-crit-idx') || '-1', 10)
        const sIdx = parseInt(target.getAttribute('data-scale-idx') || '-1', 10)
        const field = target.getAttribute('data-scale-field')
        if (cIdx >= 0 && sIdx >= 0 && editingConfig && field) {
          if (field === 'value') {
            editingConfig.criteria[cIdx].scale_levels[sIdx].value = parseInt(target.value, 10) || 0
          } else {
            editingConfig.criteria[cIdx].scale_levels[sIdx].description = target.value
          }
        }
      })
    })
  }

  // Загружаем чек-листы при монтировании
  void loadChecklists()
}
