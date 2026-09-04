/**
 * useChannels — shared channel config query.
 * Single cache entry reused by Dashboard, ScheduleCalendar, ChannelStats.
 * Channels rarely change → 5 min stale.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys, STALE, GC } from '../lib/queryClient'
import client from '../api/client'

const fetchChannels = () => client.get('/channels').then(r => r.data)

export function useChannelsQuery() {
  return useQuery({
    queryKey: queryKeys.channels(),
    queryFn: fetchChannels,
    staleTime: STALE.CONFIG,
    gcTime: GC.CONFIG,
  })
}

// Channel stats — YouTube API, expensive, cached 3 min per channel
const fetchChannelStats = (key) => client.get(`/channels/${key}/stats`).then(r => r.data)

export function useChannelStatsQuery(key, { enabled = true } = {}) {
  return useQuery({
    queryKey: queryKeys.channelStats(key),
    queryFn: () => fetchChannelStats(key),
    staleTime: STALE.CHANNEL_STATS,
    gcTime: GC.MODERATE,
    enabled: Boolean(key) && enabled,
  })
}

// Create channel
export function useCreateChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data) => client.post('/channels', data).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.channels() }),
  })
}

// Update channel
export function useUpdateChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, data }) => client.put(`/channels/${key}`, data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.channels() })
    },
  })
}

// Delete channel
export function useDeleteChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (key) => client.delete(`/channels/${key}`).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.channels() }),
  })
}

// Test Instagram credentials
export function useTestInstagram() {
  return useMutation({
    mutationFn: ({ key, data }) =>
      client.post(`/channels/${key}/instagram/test`, data).then(r => r.data),
  })
}
