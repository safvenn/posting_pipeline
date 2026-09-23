/**
 * useSettings — React Query hooks for app-wide pipeline settings.
 * Settings rarely change → 5 min stale time.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys, STALE, GC } from '../lib/queryClient'
import { getSettings, updateSettings } from '../api/settings'

export function useSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings(),
    queryFn: getSettings,
    staleTime: STALE.CONFIG,
    gcTime: GC.CONFIG,
  })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: updateSettings,
    onSuccess: (data) => {
      // Optimistically update the cache so the UI is instant
      qc.setQueryData(queryKeys.settings(), data)
    },
    onError: () => {
      // On error, re-fetch to restore truthful state
      qc.invalidateQueries({ queryKey: queryKeys.settings() })
    },
  })
}
