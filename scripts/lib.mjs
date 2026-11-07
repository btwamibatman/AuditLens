// Общие хелперы для скриптов запуска. Без зависимостей — только Node.js.
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
export const BACKEND = join(ROOT, 'backend')
export const FRONTEND = join(ROOT, 'frontend')
export const isWin = process.platform === 'win32'

const c = (code) => (s) => (process.stdout.isTTY ? `\x1b[${code}m${s}\x1b[0m` : s)
export const color = { cyan: c(36), magenta: c(35), green: c(32), yellow: c(33), red: c(31), dim: c(2), bold: c(1) }

export function loadEnv() {
  const file = join(ROOT, '.env')
  if (!existsSync(file)) return
  // Простой парсер .env (process.loadEnvFile есть не во всех версиях Node).
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([\w.]+)\s*=\s*(.*)\s*$/)
    if (!m || line.trim().startsWith('#')) continue
    const value = m[2].replace(/^(['"])(.*)\1$/, '$2')
    if (process.env[m[1]] === undefined) process.env[m[1]] = value
  }
}

export function hasCommand(cmd) {
  const r = spawnSync(cmd, ['--version'], { stdio: 'ignore', shell: isWin })
  return r.status === 0
}

export const venvPython = () =>
  join(BACKEND, '.venv', isWin ? 'Scripts' : 'bin', isWin ? 'python.exe' : 'python')

let _uv
export function useUv() {
  if (process.env.USE_UV === '0') return false
  if (_uv === undefined) _uv = hasCommand('uv')
  return _uv
}

/** Команда для запуска python внутри окружения бэкенда: uv, если есть, иначе backend/.venv. */
export function backendPython(args) {
  if (useUv()) return { cmd: 'uv', args: ['run', '--extra', 'dev', 'python', ...args] }
  return { cmd: venvPython(), args }
}

export const backendReady = () => useUv() || existsSync(venvPython())

export const childEnv = (extra = {}) => ({ ...process.env, PYTHONUTF8: '1', PYTHONUNBUFFERED: '1', ...extra })

/** Запуск с наследованием вывода. Возвращает Promise с кодом выхода. */
export function run(cmd, args, { cwd = ROOT, shell = false, env } = {}) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { cwd, stdio: 'inherit', shell, env: env ?? childEnv() })
    child.on('exit', (code) => resolve(code ?? 1))
    child.on('error', (err) => {
      console.error(color.red(`Failed to start ${cmd}: ${err.message}`))
      resolve(1)
    })
  })
}

export function runPython(args, opts = {}) {
  const { cmd, args: full } = backendPython(args)
  return run(cmd, full, { cwd: BACKEND, ...opts })
}

export function runNpm(args, opts = {}) {
  return run('npm', args, { cwd: FRONTEND, shell: isWin, ...opts })
}

export function killTree(child) {
  if (!child || child.exitCode !== null) return
  if (isWin) spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  else child.kill('SIGTERM')
}
