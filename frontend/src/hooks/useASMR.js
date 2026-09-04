/**
 * useASMR — ASMR workflow runs, foods, content, mutations.
 * ASMR runs are historical → 2 min stale.
 * Foods are static-ish → 5 min stale.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys, STALE, GC } from '../lib/queryClient'
import client from '../api/client'

// ─── Fetchers ────────────────────────────────────────────────────────────────

const fetchASMRRuns = () =>
  client.get('/asmr/runs').then(r => r.data?.items || [])

const fetchASMRFoods = () =>
  client.get('/asmr/foods?limit=50').then(r => r.data?.items || [])

const fetchASMRFoodStats = () =>
  client.get('/asmr/foods/stats').then(r => r.data || null).catch(() => null)

const fetchASMRContent = () =>
  client.get('/asmr/content').then(r => r.data?.items || []).catch(() => [])

// ─── Queries ─────────────────────────────────────────────────────────────────

export function useASMRRunsQuery() {
  return useQuery({
    queryKey: queryKeys.asmrRuns(),
    queryFn: fetchASMRRuns,
    staleTime: STALE.SLOW,
    gcTime: GC.SLOW,
  })
}

export function useASMRFoodsQuery() {
  return useQuery({
    queryKey: queryKeys.asmrFoods(),
    queryFn: fetchASMRFoods,
    staleTime: STALE.CONFIG,
    gcTime: GC.CONFIG,
  })
}

export function useASMRFoodStatsQuery() {
  return useQuery({
    queryKey: ['asmrFoodStats'],
    queryFn: fetchASMRFoodStats,
    staleTime: STALE.SLOW,
    gcTime: GC.SLOW,
  })
}

export function useASMRContentQuery() {
  return useQuery({
    queryKey: queryKeys.asmrContent(),
    queryFn: fetchASMRContent,
    staleTime: STALE.SLOW,
    gcTime: GC.SLOW,
  })
}

// ─── Mutations ────────────────────────────────────────────────────────────────

export function useTriggerASMRWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params) =>
      client.post('/asmr/trigger', params).then(r => r.data),
    onSuccess: () => {
      // Only invalidate ASMR-related queries
      qc.invalidateQueries({ queryKey: queryKeys.asmrRuns() })
      qc.invalidateQueries({ queryKey: queryKeys.asmrContent() })
    },
  })
}

export function useAddFood() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name) =>
      client.post('/asmr/foods', { name }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.asmrFoods() })
      qc.invalidateQueries({ queryKey: ['asmrFoodStats'] })
    },
  })
}

export function useDeleteFood() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) =>
      client.delete(`/asmr/foods/${id}`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.asmrFoods() })
      qc.invalidateQueries({ queryKey: ['asmrFoodStats'] })
    },
  })
}

export function useUpdateFood() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }) =>
      client.put(`/asmr/foods/${id}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.asmrFoods() })
    },
  })
}
