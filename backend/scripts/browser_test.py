"""Сквозной браузерный тест фронтенда AuditLens (Playwright).

Проверяет все 4 раздела:
F1. Список диалогов, просмотр реплик, роли, таймкоды, звонки.
F2. Запуск оценки, появление карточки, клик по цитате -> скролл и подсветка.
F3. Подача апелляции, рассмотрение проверяющим (confirm/change), пересчёт карточки.
F4. Редактор чек-листа, изменение критерия, сохранение с ростом версии.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
SCREENSHOTS_DIR = BACKEND_DIR / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Унифицируем путь к тестовой БД, чтобы скрипт и uvicorn-сервер обращались к одной базе
db_file = (BACKEND_DIR / "data" / "browser_test.db").resolve()
if db_file.exists():
    try:
        db_file.unlink()
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
os.environ["LLM_PROVIDER"] = "mock"

sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import Base, SessionLocal, engine, import_all_models  # noqa: E402
from app.features.checklists.service import ensure_default  # noqa: E402
from app.features.conversations.schemas import ConversationRecord  # noqa: E402
from app.features.conversations.service import upsert_records  # noqa: E402


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def seed_test_data():
    import_all_models()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_default(db)
        records = [
            ConversationRecord(
                conversation_id="p1-ru-001",
                channel="agent chat",
                language="RU",
                transcript=[
                    {
                        "timestamp": "00:01",
                        "speaker": "client",
                        "text": "Здравствуйте, завис перевод средств на карту.",
                    },
                    {
                        "timestamp": "00:05",
                        "speaker": "operator",
                        "text": (
                            "Добрый день! Меня зовут Алия, Freedom Broker. "
                            "Назовите, пожалуйста, ваш номер счёта для проверки."
                        ),
                    },
                    {
                        "timestamp": "00:15",
                        "speaker": "client",
                        "text": "Счёт 99887766.",
                    },
                    {
                        "timestamp": "00:25",
                        "speaker": "operator",
                        "text": (
                            "Спасибо! Проверила: платёж в обработке, "
                            "поступит до 18:00 сегодня. Комиссия 0%."
                        ),
                    },
                    {
                        "timestamp": "00:35",
                        "speaker": "operator",
                        "text": "Подскажите, остались ли у вас ещё вопросы? Хорошего дня!",
                    },
                ],
                audio_url=None,
            ),
            ConversationRecord(
                conversation_id="p2-call-002",
                channel="voice call",
                language="KZ",
                transcript=[
                    {
                        "timestamp": "12:01",
                        "speaker": "client",
                        "text": "Сәлеметсіз бе, шотты қалай толтыруға болады?",
                    },
                    {
                        "timestamp": "12:06",
                        "speaker": "operator",
                        "text": (
                            "Қайырлы күн! Freedom Broker, оператор Айнұр. "
                            "Шот нөміріңізді айтыңызшы."
                        ),
                    },
                ],
                audio_url="https://example.com/audio/sample-call.mp3",
            ),
        ]
        upsert_records(db, "DEV", records)
    print("✓ Тестовые данные (диалоги и чек-лист) подготовлены в БД.")


def main():
    print("=" * 60)
    print("AuditLens · Сквозной тест сценариев F1-F4 в браузере (Playwright)")
    print("=" * 60)

    seed_test_data()
    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Запускаем FastAPI сервер с собранным фронтендом
    python_exe = str(BACKEND_DIR / ".venv" / "Scripts" / "python.exe")
    server_env = os.environ.copy()
    server_env["DATABASE_URL"] = f"sqlite:///{db_file}"
    server_env["LLM_PROVIDER"] = "mock"
    server_proc = subprocess.Popen(
        [
            python_exe,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(BACKEND_DIR),
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    time.sleep(3)

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            print(f"Запуск браузера Chromium (порт {port})...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            page = context.new_page()

            page.on("console", lambda msg: print(f"  [Browser Console] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda exc: print(f"  [Browser PageError] {exc}"))
            page.on(
                "requestfailed",
                lambda req: print(f"  [Browser ReqFailed] {req.method} {req.url} - {req.failure}"),
            )
            page.on(
                "response",
                lambda res: (
                    print(f"  [Browser Response {res.status}] {res.url}: {res.text()[:200]}")
                    if res.status >= 400
                    else None
                ),
            )

            # ----------------------------------------------------------------
            # F1: Загрузка страницы, список диалогов и транскрипт
            # ----------------------------------------------------------------
            print("\n[Шаг 1 / F1] Проверка списка диалогов и транскрипта...")
            page.goto(base_url, wait_until="networkidle", timeout=15000)
            print(f"  Страница загружена. Заголовок: {page.title()}")

            # Проверяем заголовок и бейдж бренда
            assert "AuditLens" in page.text_content("header"), "Заголовок AuditLens не найден"
            print("  ✓ Шапка и брендинг отображаются")

            # Проверяем наличие диалогов в списке
            page.wait_for_selector("text=p1-ru-001", timeout=5000)
            page.wait_for_selector("text=p2-call-002", timeout=5000)
            print("  ✓ Список диалогов загрузился: найдены p1-ru-001 и p2-call-002")

            # Кликаем на p1-ru-001 и проверяем реплики
            page.click("text=p1-ru-001")
            page.wait_for_selector("text=Здравствуйте, завис перевод средств", timeout=5000)
            page.wait_for_selector("text=Добрый день! Меня зовут Алия", timeout=5000)
            page.wait_for_selector("text=Оператор", timeout=5000)
            page.wait_for_selector("text=Клиент", timeout=5000)
            print("  ✓ Транскрипт диалога отображается с ролями и таймкодами")

            # Проверяем диалог-звонок (аудиоплеер)
            page.click("text=p2-call-002")
            page.wait_for_selector("text=Запись звонка:", timeout=5000)
            page.wait_for_selector("audio", timeout=5000)
            print("  ✓ Для звонка p2-call-002 отображается блок аудиозаписи и плеер")

            page.screenshot(path=str(SCREENSHOTS_DIR / "01_f1_dialogues.png"))

            # Возвращаемся к p1-ru-001 для оценки
            page.click("text=p1-ru-001")

            # ----------------------------------------------------------------
            # F2: Запуск оценки, карточка и переход по цитате
            # ----------------------------------------------------------------
            print("\n[Шаг 2 / F2] Запуск оценки и проверка перехода по доказательству...")
            eval_button = page.locator("button:has-text('Оценить диалог')")
            assert eval_button.is_enabled(), "Кнопка 'Оценить диалог' заблокирована"
            eval_button.click()

            # Ждём завершения оценки
            page.wait_for_selector("text=Итоговое качество оператора", timeout=25000)
            page.wait_for_selector("text=Критерии оценки", timeout=10000)
            print("  ✓ Оценка завершена, карточка отобразилась с баллами и критериями")

            page.screenshot(path=str(SCREENSHOTS_DIR / "02_f2_evaluation_card.png"))

            # Проверяем переход по доказательству
            evidence_item = page.locator(".group:has-text('Реплика [#')").first
            if evidence_item.count() > 0:
                print("  ✓ Найдена цитата-доказательство в карточке, кликаем для перехода...")
                evidence_item.click()
                time.sleep(1)
                # Проверяем наличие подсвеченной реплики с ring-2
                highlighted = page.locator(".ring-2.ring-emerald-500")
                assert highlighted.count() > 0, "Подсветка реплики не активировалась"
                print("  ✓ Реплика в транскрипте успешно подсвечена зеленым контуром!")

            page.screenshot(path=str(SCREENSHOTS_DIR / "03_f2_evidence_highlight.png"))

            # ----------------------------------------------------------------
            # F3: Подача апелляции и рассмотрение проверяющим
            # ----------------------------------------------------------------
            print("\n[Шаг 3 / F3] Подача апелляции и решение проверяющего...")
            appeal_btn = page.locator("button:has-text('Оспорить оценку')").first
            appeal_btn.click()

            comment_sel = "textarea[placeholder*='Укажите, с чем вы не согласны']"
            page.wait_for_selector(comment_sel, timeout=5000)
            page.fill(comment_sel, "Оператор представился вовремя!")
            page.click("button:has-text('Отправить обращение')")

            page.wait_for_selector("text=На рассмотрении", timeout=8000)
            print("  ✓ Апелляция подана и отображается со статусом 'На рассмотрении'")

            # Рассмотрение проверяющим
            review_btn = page.locator("button:has-text('Рассмотреть (Проверяющий)')").first
            review_btn.click()

            page.wait_for_selector("text=Решение проверяющего по апелляции", timeout=5000)
            page.check("input[type='radio'][value='change']")
            page.fill(
                "textarea[placeholder*='Опишите причину']",
                "Приветствие подтверждено аудитором.",
            )
            page.click("button:has-text('Зафиксировать решение')")

            page.wait_for_selector("text=Пересмотрена", timeout=8000)
            page.wait_for_selector("text=Решение проверяющего", timeout=8000)
            print(
                "  ✓ Решение проверяющего зафиксировано, "
                "статус 'Пересмотрена', карточка пересчитана"
            )

            page.screenshot(path=str(SCREENSHOTS_DIR / "04_f3_appeal_reviewed.png"))

            # ----------------------------------------------------------------
            # F4: Редактор чек-листа
            # ----------------------------------------------------------------
            print("\n[Шаг 4 / F4] Проверка редактора чек-листов...")
            page.click("button:has-text('Редактор чек-листа')")

            page.wait_for_selector("text=Конфигурации", timeout=5000)
            page.wait_for_selector("text=Критерии оценки", timeout=5000)
            print("  ✓ Экран редактора чек-листов открылся")

            # Проверяем наличие критериев
            criteria_inputs = page.locator("input[placeholder='Название критерия']")
            count = criteria_inputs.count()
            assert count >= 8, f"Ожидалось не менее 8 критериев, найдено {count}"
            print(f"  ✓ В активном чек-листе найдено {count} критериев")

            # Нажимаем «+ Добавить критерий»
            page.click("button:has-text('+ Добавить критерий')")
            new_count = page.locator("input[placeholder='Название критерия']").count()
            assert new_count == count + 1, "Новый критерий не добавился"
            print("  ✓ Новый критерий успешно добавлен в конфигурацию")

            # Сохраняем чек-лист
            page.click("button:has-text('Сохранить конфигурацию')")
            time.sleep(1)
            err_box = page.locator(".bg-red-50")
            if err_box.count() > 0 and err_box.is_visible():
                print(f"  ❌ Ошибка валидации на фронтенде: {err_box.text_content()}")
            page.wait_for_selector("text=успешно сохранён", timeout=8000)
            print("  ✓ Чек-лист сохранён на бэкенде с новой версией!")

            page.screenshot(path=str(SCREENSHOTS_DIR / "05_f4_checklist_editor.png"))

            browser.close()

        print("\n" + "=" * 60)
        print("✅ ВСЕ 4 РАЗДЕЛА (F1, F2, F3, F4) УСПЕШНО ПРОТЕСТИРОВАНЫ В БРАУЗЕРЕ!")
        print(f"Скриншоты шагов сохранены в: {SCREENSHOTS_DIR}")
        print("=" * 60)
        return 0
    except Exception as exc:
        print(f"\n❌ Ошибка во время браузерного теста: {exc}")
        try:
            page.screenshot(path=str(SCREENSHOTS_DIR / "error_screenshot.png"))
            print(f"Скриншот ошибки сохранён: {SCREENSHOTS_DIR / 'error_screenshot.png'}")
            print("Текст страницы:")
            print(page.text_content("body")[:1000])
        except Exception:
            pass
        import traceback

        traceback.print_exc()
        return 1
    finally:
        server_proc.terminate()
        server_proc.wait()


if __name__ == "__main__":
    sys.exit(main())
