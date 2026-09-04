/**
 * useSchedule — schedule calendar query + reschedule mutation.
 * Shares channel data with useChannelsQuery (no duplicate fetch).
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys, STALE, GC } from '../lib/queryClient'
import client from '../api/client'

const fetchSchedule = (days) => client.get('/schedule', { params: { days } }).then(r => r.data)

export function useScheduleQuery(days = 7) {
  return useQuery({
    queryKey: queryKeys.schedule(days),
    queryFn: () => fetchSchedule(days),
    staleTime: STALE.MODERATE,
    gcTime: GC.MODERATE,
    // Keep old schedule visible while fetching new days range
    placeholderData: (prev) => prev,
  })
}

export function useReschedule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data) => client.post('/schedule/reschedule', data).then(r => r.data),
    onSuccess: () => {
      // Invalidate all schedule variants (any days range)
      qc.invalidateQueries({ queryKey: ['schedule'] })
      // Also invalidate post list (scheduled_at changed)
      qc.invalidateQueries({ queryKey: ['posts'] })
    },
  })
}

export function useClearFailedSchedules() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => client.post('/schedule/clear-failed').then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedule'] })
      qc.invalidateQueries({ queryKey: ['posts'] })
    },
  })
}

export function useDeleteScheduledVideo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data) => client.post('/schedule/delete', data).then(r => r.data),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ['schedule'] })
      qc.invalidateQueries({ queryKey: ['posts'] })
      if (vars?.post_id) {
        qc.removeQueries({ queryKey: queryKeys.post(vars.post_id) })
      }
    },
  })
}
