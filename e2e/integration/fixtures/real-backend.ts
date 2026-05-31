import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'

const BACKEND_DIR = path.resolve('./backend')
const UVICORN_EXE = path.join(BACKEND_DIR, '.venv', 'Scripts', 'uvicorn.exe')
const INTEGRATION_PORT = 8001
const HEALTH_URL = `http://localhost:${INTEGRATION_PORT}/health`
const STARTUP_TIMEOUT_MS = 20_000

let backendProcess: ChildProcess | null = null

export default async function globalSetup() {
  if (!fs.existsSync(UVICORN_EXE)) {
    throw new Error(
      `uvicorn.exe not found at ${UVICORN_EXE}.\n` +
      `Run: cd backend && venv\\Scripts\\pip install uvicorn`
    )
  }

  console.log(`[integration] Starting backend on port ${INTEGRATION_PORT}...`)

  backendProcess = spawn(UVICORN_EXE, ['app.main:app', '--port', String(INTEGRATION_PORT)], {
    cwd: BACKEND_DIR,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONPATH: BACKEND_DIR,
      DATABASE_URL: 'sqlite+aiosqlite:///./integration_test.db',
    },
  })

  backendProcess.stdout?.on('data', (d) => process.stdout.write(`[uvicorn] ${d}`))
  backendProcess.stderr?.on('data', (d) => process.stderr.write(`[uvicorn] ${d}`))

  backendProcess.on('exit', (code) => {
    if (code !== null && code !== 0) {
      console.error(`[integration] Backend exited with code ${code}`)
    }
  })

  const deadline = Date.now() + STARTUP_TIMEOUT_MS
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 500))
    try {
      const res = await fetch(HEALTH_URL)
      if (res.ok) {
        console.log(`[integration] Backend ready at ${HEALTH_URL}`)
        process.env.INTEGRATION_BACKEND_PID = String(backendProcess.pid)
        return
      }
    } catch {
      // Not ready yet — keep polling
    }
  }

  backendProcess.kill()
  throw new Error(`Backend failed to start within ${STARTUP_TIMEOUT_MS}ms. Check uvicorn logs above.`)
}

export async function teardown() {
  const pid = process.env.INTEGRATION_BACKEND_PID
  if (pid) {
    try {
      process.kill(parseInt(pid))
      console.log(`[integration] Backend process ${pid} stopped`)
    } catch {
      // Already stopped
    }
  }
}
