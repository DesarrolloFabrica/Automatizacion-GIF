import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, isMissingJobResponse, readApiErrorDetail } from '../lib/api'
import type { JobStatusResponse, PromptType } from '../types/granules'

const JOB_QUERY_KEY = (jobId: string) => ['job', jobId]
const JOB_REFETCH_INTERVAL_MS = 3000
const JOB_STALE_TIME_MS = 0
const JOB_GC_TIME_MS = 5 * 60 * 1000
const JOB_RETRY_COUNT = 0

function isJobActive(status: string | undefined): boolean {
  return status === 'running' || status === 'queued'
}

function isJobTerminal(status: string | undefined): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled'
}

export function useJobStatus(jobId: string | null | undefined, options?: {
  onMissing?: () => void
  onTerminal?: (payload: JobStatusResponse) => void
  enabled?: boolean
}) {
  return useQuery({
    queryKey: JOB_QUERY_KEY(jobId ?? ''),
    queryFn: async () => {
      if (!jobId) throw new Error('No jobId')
      const response = await apiFetch(`/api/jobs/${jobId}`)
      if (isMissingJobResponse(response)) {
        throw new Error('MISSING_JOB')
      }
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No fue posible consultar el estado del job.'))
      }
      return (await response.json()) as JobStatusResponse
    },
    enabled: Boolean(jobId) && (options?.enabled ?? true),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return JOB_REFETCH_INTERVAL_MS
      if (isJobTerminal(data.status)) return false
      if (isJobActive(data.status)) return JOB_REFETCH_INTERVAL_MS
      return false
    },
    refetchOnWindowFocus: false,
    refetchOnMount: true,
    retry: JOB_RETRY_COUNT,
    staleTime: JOB_STALE_TIME_MS,
    gcTime: JOB_GC_TIME_MS,
    throwOnError: false,
    meta: {
      onError: (error: Error) => {
        if (error.message === 'MISSING_JOB') {
          options?.onMissing?.()
        }
      },
    },
  })
}

export function useCreateJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ syllabus, nivel }: { syllabus: File; nivel: PromptType }) => {
      const formData = new FormData()
      formData.append('syllabus', syllabus)
      formData.append('nivel', nivel)
      const response = await apiFetch('/api/jobs', { method: 'POST', body: formData })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo crear el job.'))
      }
      return (await response.json()) as { jobId: string; status: string }
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(data.jobId) })
    },
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (jobId: string) => {
      const response = await apiFetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo cancelar el job.'))
      }
      return (await response.json()) as { jobId: string; processTerminated: boolean; message: string }
    },
    onSuccess: (_, jobId) => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(jobId) })
    },
  })
}

export function useRunPipelineLocal() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (jobId: string) => {
      const response = await apiFetch(`/api/jobs/${jobId}/pipeline-local`, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo iniciar TXT/DOCX.'))
      }
      return (await response.json()) as { jobId: string; status: string }
    },
    onSuccess: (_, jobId) => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(jobId) })
    },
  })
}

export function useRunMaterials() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (jobId: string) => {
      const response = await apiFetch(`/api/jobs/${jobId}/materials`, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo iniciar materiales.'))
      }
      return (await response.json()) as { jobId: string; status: string }
    },
    onSuccess: (_, jobId) => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(jobId) })
    },
  })
}

export function useRetryGranules() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (jobId: string) => {
      const response = await apiFetch(`/api/jobs/${jobId}/retry-granules`, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo reintentar gránulos.'))
      }
      return (await response.json()) as { jobId: string; status: string }
    },
    onSuccess: (_, jobId) => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(jobId) })
    },
  })
}

export function useRetryPipelineLocal() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (jobId: string) => {
      const response = await apiFetch(`/api/jobs/${jobId}/retry-pipeline-local`, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo reintentar TXT/DOCX.'))
      }
      return (await response.json()) as { jobId: string; status: string }
    },
    onSuccess: (_, jobId) => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(jobId) })
    },
  })
}

export function useRetryMaterials() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (jobId: string) => {
      const response = await apiFetch(`/api/jobs/${jobId}/retry-materials`, { method: 'POST' })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo reintentar materiales.'))
      }
      return (await response.json()) as { jobId: string; status: string }
    },
    onSuccess: (_, jobId) => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(jobId) })
    },
  })
}

export function useDriveUpload(jobId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ driveFolderId, includeZip, phase }: { driveFolderId: string; includeZip?: boolean; phase?: string }) => {
      const formData = new FormData()
      formData.append('driveFolderId', driveFolderId)
      formData.append('includeZip', includeZip === false ? 'false' : 'true')
      if (phase) formData.append('phase', phase)
      const response = await apiFetch(`/api/jobs/${jobId}/upload-drive`, { method: 'POST', body: formData })
      if (!response.ok) {
        throw new Error(await readApiErrorDetail(response, 'No se pudo subir a Drive.'))
      }
      return await response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: JOB_QUERY_KEY(jobId) })
    },
  })
}

export function useSyllabusPreview() {
  return useMutation({
    mutationFn: async (syllabus: File) => {
      const formData = new FormData()
      formData.append('syllabus', syllabus)
      const response = await apiFetch('/api/syllabus/preview', { method: 'POST', body: formData })
      if (!response.ok) {
        const payload = (await response.json()) as { detail?: string }
        throw new Error(payload.detail ?? 'No fue posible analizar el syllabus.')
      }
      return await response.json()
    },
  })
}
