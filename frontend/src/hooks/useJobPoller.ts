import { useCallback, useEffect, useRef, useState } from 'react'
import { apiFetch, isMissingJobResponse, readApiErrorDetail } from '../lib/api'
import type { JobStatusResponse } from '../types/granules'

export type PollerStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'missing_job'
  | 'recoverable_error'

export interface UseJobPollerOptions {
  intervalMs?: number
  maxConsecutiveErrors?: number
  timeoutMs?: number
  onStatus?: (payload: JobStatusResponse) => void
  onComplete?: (payload: JobStatusResponse) => void
  onFailed?: (payload: JobStatusResponse) => void
  onCancelled?: (payload: JobStatusResponse) => void
  onMissing?: (error: string) => void
  onRecoverableError?: (error: string) => void
}

const DEFAULT_INTERVAL_MS = 3000
const DEFAULT_MAX_ERRORS = 3
const DEFAULT_TIMEOUT_MS = 120 * 60 * 1000
const MISSING_JOB_MESSAGE = 'El proceso ya no existe, fue limpiado o el backend se reinició.'

const ACTIVE_POLLERS = new Map<string, boolean>()

function isPollableStatus(status: string): boolean {
  return status === 'queued' || status === 'running'
}

export function useJobPoller(options: UseJobPollerOptions = {}) {
  const {
    intervalMs = DEFAULT_INTERVAL_MS,
    maxConsecutiveErrors = DEFAULT_MAX_ERRORS,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = options

  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [pollerStatus, setPollerStatus] = useState<PollerStatus>('idle')

  const intervalRef = useRef<number | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const consecutiveErrorsRef = useRef(0)
  const startedAtRef = useRef<number>(0)
  const isRunningRef = useRef(false)
  const currentJobIdRef = useRef<string | null>(null)
  const optionsRef = useRef(options)

  optionsRef.current = options

  const clearPolling = useCallback(() => {
    if (intervalRef.current) {
      window.clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    isRunningRef.current = false
    consecutiveErrorsRef.current = 0
    if (currentJobIdRef.current) {
      ACTIVE_POLLERS.delete(currentJobIdRef.current)
    }
  }, [])

  const stop = useCallback(() => {
    clearPolling()
    setActiveJobId(null)
    setPollerStatus('idle')
  }, [clearPolling])

  const pollOnce = useCallback(async (jobId: string): Promise<boolean> => {
    const opts = optionsRef.current
    const controller = new AbortController()
    abortRef.current = controller

    try {
      if (Date.now() - startedAtRef.current > timeoutMs) {
        clearPolling()
        setPollerStatus('recoverable_error')
        const msg = `Tiempo máximo de espera agotado (${Math.round(timeoutMs / 60000)} min).`
        opts.onRecoverableError?.(msg)
        return false
      }

      const response = await apiFetch(`/api/jobs/${jobId}`, { signal: controller.signal })

      if (isMissingJobResponse(response)) {
        clearPolling()
        setPollerStatus('missing_job')
        opts.onMissing?.(MISSING_JOB_MESSAGE)
        return false
      }

      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No fue posible consultar el estado del job.'))
      }

      const payload = (await response.json()) as JobStatusResponse
      consecutiveErrorsRef.current = 0
      opts.onStatus?.(payload)

      if (payload.status === 'completed') {
        clearPolling()
        setPollerStatus('completed')
        opts.onComplete?.(payload)
        return false
      }

      if (payload.status === 'failed') {
        clearPolling()
        setPollerStatus('failed')
        opts.onFailed?.(payload)
        return false
      }

      if (payload.status === 'cancelled') {
        clearPolling()
        setPollerStatus('cancelled')
        opts.onCancelled?.(payload)
        return false
      }

      if (!isPollableStatus(payload.status)) {
        clearPolling()
        setPollerStatus('idle')
        return false
      }

      setPollerStatus('running')
      return true
    } catch (error) {
      if (controller.signal.aborted) return false

      consecutiveErrorsRef.current += 1
      if (consecutiveErrorsRef.current >= maxConsecutiveErrors) {
        clearPolling()
        setPollerStatus('recoverable_error')
        const msg = error instanceof Error ? error.message : 'No fue posible consultar el backend tras varios intentos.'
        opts.onRecoverableError?.(msg)
        return false
      }
      return true
    }
  }, [clearPolling, maxConsecutiveErrors, timeoutMs])

  const start = useCallback((jobId: string) => {
    if (!jobId?.trim()) return
    if (ACTIVE_POLLERS.has(jobId)) return

    clearPolling()
    setActiveJobId(jobId)
    setPollerStatus('running')
    currentJobIdRef.current = jobId
    startedAtRef.current = Date.now()
    consecutiveErrorsRef.current = 0
    isRunningRef.current = true
    ACTIVE_POLLERS.set(jobId, true)

    const tick = async () => {
      if (!isRunningRef.current) return
      const shouldContinue = await pollOnce(jobId)
      if (!shouldContinue) return
    }

    void tick()
    intervalRef.current = window.setInterval(tick, intervalMs)
  }, [clearPolling, intervalMs, pollOnce])

  const restart = useCallback((jobId: string) => {
    clearPolling()
    start(jobId)
  }, [clearPolling, start])

  useEffect(() => {
    return () => {
      clearPolling()
    }
  }, [clearPolling])

  return {
    activeJobId,
    pollerStatus,
    start,
    stop,
    restart,
    clearPolling,
  }
}
