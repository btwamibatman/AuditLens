// Запуск python внутри окружения бэкенда (cwd = backend/):
//   node scripts/py.mjs -m alembic upgrade head
import { loadEnv, runPython } from './lib.mjs'

loadEnv()
process.exit(await runPython(process.argv.slice(2)))
