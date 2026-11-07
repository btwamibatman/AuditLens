// npm run dev        — бэкенд + фронтенд одной командой
// npm run dev:api    — только бэкенд
// npm run dev:web    — только фронтенд
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import {
  BACKEND, FRONTEND, backendPython, backendReady, childEnv, color, isWin, killTree, loadEnv, runPython,
} from './lib.mjs'

loadEnv()
const only = process.argv[2] // 'api' | 'web' | undefined
const apiPort = process.env.API_PORT || '8000'
const webPort = process.env.WEB_PORT || '5173'

if (only !== 'web' && !backendReady()) {
  console.error(color.red('Окружение бэкенда не найдено. Сначала выполните: npm run setup'))
  process.exit(1)
}
if (only !== 'api' && !existsSync(join(FRONTEND, 'node_modules'))) {
  console.error(color.red('Нет frontend/node_modules. Сначала выполните: npm run setup'))
  process.exit(1)
}

const children = []

function start(name, paint, cmd, args, opts) {
  const child = spawn(cmd, args, { ...opts, env: childEnv({ FORCE_COLOR: '1' }) })
  const tag = paint(`[${name}]`)
  const pipe = (stream, out) => {
    let buf = ''
    stream.on('data', (d) => {
      buf += d.toString()
      const lines = buf.split(/\r?\n/)
      buf = lines.pop()
      for (const line of lines) out.write(`${tag} ${line}\n`)
    })
  }
  pipe(child.stdout, process.stdout)
  pipe(child.stderr, process.stderr)
  child.on('exit', (code) => {
    console.log(`${tag} exited with code ${code}`)
    shutdown(code ?? 0)
  })
  children.push(child)
}

let stopping = false
function shutdown(code = 0) {
  if (stopping) return
  stopping = true
  children.forEach(killTree)
  process.exit(code)
}
process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))

if (only !== 'web') {
  // Миграции перед стартом — товарищ по команде мог добавить новую.
  if ((await runPython(['-m', 'alembic', 'upgrade', 'head'])) !== 0) {
    console.error(color.red('Миграции не применились — проверьте DATABASE_URL и backend/migrations'))
    process.exit(1)
  }
  const py = backendPython(['-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', apiPort])
  start('api', color.cyan, py.cmd, py.args, { cwd: BACKEND })
}
if (only !== 'api') {
  start('web', color.magenta, 'npm', ['run', 'dev'], { cwd: FRONTEND, shell: isWin })
}

console.log(
  `\n  ${color.bold('Frontend')}  http://localhost:${webPort}` +
    `\n  ${color.bold('API docs')}  http://localhost:${apiPort}/api/docs\n`,
)
