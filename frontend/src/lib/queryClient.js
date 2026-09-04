/**
 * Central QueryClient configuration.
 * staleTime = how long data is considered fresh (no background refetch)
 * gcTime    = how long unused data stays in memory (was cacheTime in v4)
 *
 * Per-query stale policy overview:
 *  channels          — rarely change, 5 min fresh
 *  posts list        — pipeline is active, 15s fresh
 *  running job       — near-real-time, 4s refetch interval
 *  post detail       — depends on status (active: 10s, done: 5 min)
 *  schedule          — 30s fresh
 *  failed jobs       — 30s fresh
 *  ASMR runs         — historical, 2 min fresh
 *  ASMR foods        — static-ish, 5 min fresh
 *  channel stats     — YouTube API expensive, 3 min fresh
 */
import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Default: treat data stale after 30s
      staleTime: 30_000,
      // Keep unused data in cache 5 minutes by default
      gcTime: 5 * 60_000,
      // Retry once on failure (Render cold starts)
      retry: 1,
      retryDelay: 2000,
      // Don't refetch just because window regained focus while data is fresh
      refetchOnWindowFocus: true,
      // Don't refetch on reconnect if still fresh
      refetchOnReconnect: true,
    },
    mutations: {
      retry: 0,
    },
  },
})

// ─── Query Key Factory ──────────────────────────────────────────────────────
// Central registry of all query keys for consistent invalidation.

export const queryKeys = {
  // Channels
  channels: () => ['channels'],
  channelStats: (key) => ['channelStats', key],

  // Posts
  posts: (params = {}) => ['posts', params],
  post: (id) => ['post', String(id)],
  runningJob: () => ['runningJob'],

  // Schedule
  schedule: (days) => ['schedule', days],

  // ASMR
  asmrRuns: () => ['asmrRuns'],
  asmrFoods: () => ['asmrFoods'],
  asmrContent: () => ['asmrContent'],
}

// ─── Stale Time Constants ───────────────────────────────────────────────────

export const STALE = {
  /** 4 seconds — running job, active cleaning status */
  REALTIME: 4_000,
  /** 10 seconds — active post detail (cleaning/scheduled) */
  ACTIVE: 10_000,
  /** 15 seconds — post list (pipeline is live) */
  POSTS: 15_000,
  /** 30 seconds — schedule, failed jobs */
  MODERATE: 30_000,
  /** 2 minutes — ASMR runs (historical) */
  SLOW: 2 * 60_000,
  /** 3 minutes — channel YouTube stats (expensive API) */
  CHANNEL_STATS: 3 * 60_000,
  /** 5 minutes — channels config, ASMR foods */
  CONFIG: 5 * 60_000,
}

export const GC = {
  REALTIME: 60_000,
  ACTIVE: 5 * 60_000,
  MODERATE: 10 * 60_000,
  SLOW: 30 * 60_000,
  CONFIG: 60 * 60_000,
}
