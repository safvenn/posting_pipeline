/**
 * usePosts — post list, post detail, running job, mutations.
 *
 * Cache policy:
 *  - Post list:    15s stale (pipeline is active)
 *  - Running job:  4s refetch interval (near-real-time cleaning progress)
 *  - Post detail:  10s for active statuses, 5 min for terminal statuses
 *
 * Mutations only invalidate affected query keys — not unrelated pages.
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { queryKeys, STALE, GC } from '../lib/queryClient'
import client from '../api/client'

// ─── Active terminal statuses (no need for fast polling) ────────────────────
const TERMINAL_STATUSES = new Set(['commented', 'failed'])
const ACTIVE_STATUSES = new Set(['queued', 'cleaning', 'cleaned', 'scheduled', 'uploaded'])

// ─── Fetchers ───────────────────────────────────────────────────────────────

const fetchPosts = (params) => client.get('/posts', { params }).then(r => r.data)
const fetchPost = (id) => client.get(`/posts/${id}`).then(r => r.data)

// ─── Queries ────────────────────────────────────────────────────────────────

export function usePostsQuery(params = {}) {
  return useQuery({
    queryKey: queryKeys.posts(params),
    queryFn: () => fetchPosts(params),
    staleTime: STALE.POSTS,
    gcTime: GC.ACTIVE,
    // Keep previous data visible while fetching new (no blank flash on filter change)
    placeholderData: (prev) => prev,
  })
}

export function usePostQuery(id) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: queryKeys.post(id),
    queryFn: () => fetchPost(id),
    enabled: Boolean(id),
    staleTime: (data) => {
      // Terminal posts: fresh for 5 min (no need to poll)
      if (data && TERMINAL_STATUSES.has(data.status)) return STALE.CONFIG
      // Active posts: fresh for 10s (cleaning progress)
      return STALE.ACTIVE
    },
    gcTime: GC.ACTIVE,
    refetchInterval: (query) => {
      const data = query.state.data
      // Active posts: background poll every 10s
      if (data && ACTIVE_STATUSES.has(data.status)) return STALE.ACTIVE
      // Terminal: no auto-poll
      return false
    },
    // Seed from the posts list cache if available (instant display)
    initialData: () => {
      const allCaches = qc.getQueriesData({ queryKey: ['posts'] })
      for (const [, data] of allCaches) {
        const found = data?.items?.find(p => String(p.id) === String(id))
        if (found) return found
      }
      return undefined
    },
    initialDataUpdatedAt: () => {
      // Consider seeded data from list as 10s old (triggers background refresh)
      const allCaches = qc.getQueriesData({ queryKey: ['posts'] })
      for (const [, data] of allCaches) {
        const found = data?.items?.find(p => String(p.id) === String(id))
        if (found) return Date.now() - 10_000
      }
      return undefined
    },
  })
}

/**
 * Running job — polls /posts?status=cleaning every 4s.
 * Separate cache entry from the full posts list so it doesn't
 * cause the full Dashboard table to re-render on every 4s tick.
 */
export function useRunningJobQuery() {
  return useQuery({
    queryKey: queryKeys.runningJob(),
    queryFn: () =>
      client.get('/posts', { params: { status: 'cleaning' } })
        .then(r => r.data?.items?.[0] || null)
        .catch(() => null),
    staleTime: STALE.REALTIME,
    gcTime: GC.REALTIME,
    refetchInterval: STALE.REALTIME,
    refetchIntervalInBackground: false,
  })
}


// ─── Mutations ──────────────────────────────────────────────────────────────

export function useRetryPost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => client.post(`/posts/${id}/retry`).then(r => r.data),
    onSuccess: (_, id) => {
      // Invalidate only this post's detail + post lists (schedule unchanged)
      qc.invalidateQueries({ queryKey: queryKeys.post(id) })
      qc.invalidateQueries({ queryKey: ['posts'] })
      qc.invalidateQueries({ queryKey: queryKeys.runningJob() })
    },
  })
}

export function useDeletePost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => client.delete(`/posts/${id}`).then(r => r.data),
    onSuccess: (_, id) => {
      // Remove from cache immediately (optimistic)
      qc.removeQueries({ queryKey: queryKeys.post(id) })
      qc.invalidateQueries({ queryKey: ['posts'] })
    },
  })
}

export function useCancelPost() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => client.post(`/posts/${id}/cancel`).then(r => r.data),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: queryKeys.post(id) })
      qc.invalidateQueries({ queryKey: ['posts'] })
      qc.invalidateQueries({ queryKey: queryKeys.runningJob() })
    },
  })
}

export function usePublishInstagramReel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id) => client.post(`/posts/${id}/instagram/publish`).then(r => r.data),
    onSuccess: (_, id) => {
      qc.invalidateQueries({ queryKey: queryKeys.post(id) })
      qc.invalidateQueries({ queryKey: ['posts'] })
    },
  })
}

export function useResetStuck() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => client.post('/posts/reset-stuck').then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['posts'] })
      qc.invalidateQueries({ queryKey: queryKeys.runningJob() })
    },
  })
}

export function useClearFailedPosts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => client.delete('/posts/failed/clear').then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['posts'] }),
  })
}
