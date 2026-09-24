import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys, STALE, GC } from '../lib/queryClient'
import {
  getMetrics,
  getJobStats,
  getJobs,
  getDeadLetterJobs,
  getCircuitBreakerStatus,
  resetCircuitBreaker,
  requeueAllDeadLetters,
  retryJob,
  cancelJob,
  getSecurityStatus,
  rotateSecret,
} from '../api/operations'

// ── Metrics ────────────────────────────────────────────────────────
export function useMetricsQuery({ refetchInterval = false } = {}) {
  return useQuery({
    queryKey: queryKeys.metrics(),
    queryFn: getMetrics,
    staleTime: STALE.REALTIME,
    gcTime: GC.REALTIME,
    refetchInterval,
  })
}

// ── Job Tracker & DLQ ──────────────────────────────────────────────
export function useJobStatsQuery({ refetchInterval = false } = {}) {
  return useQuery({
    queryKey: queryKeys.jobStats(),
    queryFn: getJobStats,
    staleTime: STALE.ACTIVE,
    gcTime: GC.ACTIVE,
    refetchInterval,
  })
}

export function useJobsQuery(params = {}, { refetchInterval = false } = {}) {
  return useQuery({
    queryKey: queryKeys.jobs(params),
    queryFn: () => getJobs(params),
    staleTime: STALE.ACTIVE,
    gcTime: GC.ACTIVE,
    refetchInterval,
  })
}

export function useCircuitBreakerQuery() {
  return useQuery({
    queryKey: queryKeys.circuitBreaker(),
    queryFn: getCircuitBreakerStatus,
    staleTime: STALE.ACTIVE,
    gcTime: GC.ACTIVE,
  })
}

export function useDeadLettersQuery() {
  return useQuery({
    queryKey: queryKeys.deadLetters(),
    queryFn: getDeadLetterJobs,
    staleTime: STALE.MODERATE,
    gcTime: GC.MODERATE,
  })
}

export function useResetCircuitBreaker() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: resetCircuitBreaker,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.circuitBreaker() })
      qc.invalidateQueries({ queryKey: queryKeys.jobStats() })
      qc.invalidateQueries({ queryKey: queryKeys.metrics() })
    },
  })
}

export function useRequeueDeadLetters() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: requeueAllDeadLetters,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.jobStats() })
      qc.invalidateQueries({ queryKey: queryKeys.deadLetters() })
      qc.invalidateQueries({ queryKey: queryKeys.jobs() })
      qc.invalidateQueries({ queryKey: queryKeys.metrics() })
    },
  })
}

export function useRetryJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId) => retryJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.jobs() })
      qc.invalidateQueries({ queryKey: queryKeys.jobStats() })
      qc.invalidateQueries({ queryKey: queryKeys.metrics() })
    },
  })
}

export function useCancelJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId) => cancelJob(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.jobs() })
      qc.invalidateQueries({ queryKey: queryKeys.jobStats() })
    },
  })
}

// ── Security Health ────────────────────────────────────────────────
export function useSecurityStatusQuery() {
  return useQuery({
    queryKey: queryKeys.securityStatus(),
    queryFn: getSecurityStatus,
    staleTime: STALE.CONFIG,
    gcTime: GC.CONFIG,
  })
}

export function useRotateSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (newSecret) => rotateSecret(newSecret),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.securityStatus() })
      qc.invalidateQueries({ queryKey: queryKeys.metrics() })
    },
  })
}
