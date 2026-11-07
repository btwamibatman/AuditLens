import { loadEnv, runPython } from './lib.mjs'

loadEnv()
process.exit(await runPython(process.argv.slice(2)))
