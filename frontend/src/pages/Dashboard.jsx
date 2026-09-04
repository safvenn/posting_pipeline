import React, { useState, useMemo, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  RefreshCw,
  Search,
  Upload,
  Calendar,
  Layers,
  Clock,
  PlayCircle,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  ExternalLink,
  Download,
  Terminal,
  Activity,
  ChevronLeft,
  ChevronRight,
  Tv2,
  MoreVertical,
  Bell,
  Settings,
  User,
  Check,
  AlertCircle,
  Hourglass,
  Sliders,
} from 'lucide-react'
import StatusBadge from '../components/StatusBadge'
import RunningJobBanner from '../components/RunningJobBanner'
import { usePostsQuery, useRunningJobQuery, useResetStuck } from '../hooks/usePosts'
import { useChannelsQuery } from '../hooks/useChannels'
import { parseUTCDate } from '../utils/timeFormat'

const STATUSES = [
  { id: 'all', label: 'All Statuses' },
  { id: 'queued', label: 'Queued' },
  { id: 'cleaning', label: 'Cleaning' },
  { id: 'cleaned', label: 'Cleaned' },
  { id: 'scheduled', label: 'Scheduled' },
  { id: 'commented', label: 'Commented' },
  { id: 'failed', label: 'Failed' },
]

function fmtTime(isoStr) {
  if (!isoStr) return '—'
  const d = parseUTCDate(isoStr)
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })
}

export default function Dashboard() {
  const [channel, setChannel] = useState('all')
  const [status, setStatus] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [resetMsg, setResetMsg] = useState('')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const searchInputRef = useRef(null)
  const navigate = useNavigate()

  // Memoized query params for posts
  const postParams = useMemo(() => {
    const p = {}
    if (channel !== 'all') p.channel = channel
    if (status !== 'all') p.status = status
    return p
  }, [channel, status])

  const {
    data: postData,
    isFetching: postsFetching,
    refetch: refetchPosts,
  } = usePostsQuery(postParams)

  const { data: channels = [] } = useChannelsQuery()
  const { data: runningJobData } = useRunningJobQuery()
  const resetStuck = useResetStuck()

  const rawPosts = postData?.items || []
  const total = postData?.total || rawPosts.length

  // Client-side text search filtering
  const posts = useMemo(() => {
    if (!searchQuery.trim()) return rawPosts
    const q = searchQuery.toLowerCase().trim()
    return rawPosts.filter(p => {
      const matchId = String(p.id).includes(q)
      const matchTitle = (p.title || '').toLowerCase().includes(q)
      const matchEnriched = (p.enriched_title || '').toLowerCase().includes(q)
      const matchChannel = (p.channel || '').toLowerCase().includes(q)
      const matchYt = (p.youtube_video_id || '').toLowerCase().includes(q)
      return matchId || matchTitle || matchEnriched || matchChannel || matchYt
    })
  }, [rawPosts, searchQuery])

  // Aggregate KPI stats across current dataset
  const totalCount = rawPosts.length
  const inPipelineCount = useMemo(
    () => rawPosts.filter(p => ['queued', 'cleaning', 'cleaned'].includes(p.status)).length,
    [rawPosts]
  )
  const scheduledCount = useMemo(
    () => rawPosts.filter(p => ['scheduled', 'uploaded'].includes(p.status)).length,
    [rawPosts]
  )
  const completedCount = useMemo(
    () => rawPosts.filter(p => p.status === 'commented').length,
    [rawPosts]
  )
  const failedCount = useMemo(
    () => rawPosts.filter(p => p.status === 'failed').length,
    [rawPosts]
  )
  const queuedCount = useMemo(
    () => rawPosts.filter(p => p.status === 'queued').length,
    [rawPosts]
  )
  const stuckCount = useMemo(
    () => rawPosts.filter(p => ['cleaning', 'cleaned'].includes(p.status)).length,
    [rawPosts]
  )

  // Channel post counts
  const channelCounts = useMemo(() => {
    const map = {}
    rawPosts.forEach(p => {
      if (p.channel) {
        map[p.channel] = (map[p.channel] || 0) + 1
      }
    })
    return map
  }, [rawPosts])

  // Global Cmd+K / Ctrl+K keyboard shortcut
  useEffect(() => {
    function handleKeyDown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        if (searchInputRef.current) {
          searchInputRef.current.focus()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  async function handleRefresh() {
    setIsRefreshing(true)
    await refetchPosts()
    setTimeout(() => setIsRefreshing(false), 700)
  }

  async function handleResetStuck() {
    try {
      const res = await resetStuck.mutateAsync()
      setResetMsg(res.message || 'Reset complete')
      setTimeout(() => setResetMsg(''), 5000)
    } catch (err) {
      setResetMsg('Reset failed: ' + (err?.response?.data?.detail || err.message))
      setTimeout(() => setResetMsg(''), 5000)
    }
  }

  function exportCSV() {
    if (!posts.length) return
    const headers = ['ID', 'Title', 'Enriched Title', 'Channel', 'Status', 'Scheduled At', 'YouTube ID', 'Created At']
    const rows = posts.map(p => [
      p.id,
      `"${(p.title || '').replace(/"/g, '""')}"`,
      `"${(p.enriched_title || '').replace(/"/g, '""')}"`,
      `"${p.channel || ''}"`,
      p.status,
      p.scheduled_at || '',
      p.youtube_video_id || '',
      p.created_at || '',
    ])
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement('a')
    link.setAttribute('href', encodedUri)
    link.setAttribute('download', `yt-pipeline-posts-${new Date().toISOString().slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  const isInitialLoad = !postData && postsFetching

  return (
    <div className="dashboard-root flex-1 flex flex-col min-w-0 bg-surface-base">
      {/* ===================================================================== */}
      {/* TOP NAVIGATION BAR (Persistent Header)                                 */}
      {/* ===================================================================== */}
      <header className="sticky top-0 right-0 z-30 h-14 w-full px-6 flex justify-between items-center border-b border-border-subtle bg-surface-base/80 backdrop-blur-md">
        {/* Left: Page Title & Meta */}
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-on-surface tracking-tight">
            Pipeline Dashboard
          </h2>
          <span className="bg-status-success/15 text-status-success border border-status-success/30 px-2 py-0.5 rounded text-mono-data-sm text-[11px] flex items-center gap-1.5 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-status-success animate-ping" />
            Live Synced
          </span>
        </div>

        {/* Right Controls */}
        <div className="flex items-center gap-2.5">
          {/* Search bar with Cmd+K */}
          <div className="relative hidden md:block w-72">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-outline pointer-events-none"
            />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Filter jobs, tags, ID..."
              className="h-8 w-full pl-9 pr-12 bg-surface-1 border border-border-subtle rounded-lg text-xs text-on-surface placeholder-outline focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all"
            />
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] font-mono text-outline bg-surface-2 px-1.5 py-0.5 rounded border border-border-subtle pointer-events-none">
              ⌘K
            </span>
          </div>

          {/* Reset stuck action button if jobs are stuck */}
          {stuckCount > 0 && (
            <button
              onClick={handleResetStuck}
              className="h-8 flex items-center gap-1.5 px-3 bg-status-warning/10 border border-status-warning/30 text-status-warning hover:bg-status-warning/20 rounded-lg text-xs font-medium transition-all active:scale-95"
              title={`${stuckCount} stuck job(s) in cleaned/cleaning — click to re-queue`}
            >
              <RotateCcw size={13} />
              <span>Reset Stuck ({stuckCount})</span>
            </button>
          )}

          {/* Refresh Action */}
          <button
            onClick={handleRefresh}
            disabled={postsFetching}
            className="h-8 flex items-center gap-1.5 px-3 bg-surface-2 border border-border-strong text-on-surface hover:bg-surface-3 rounded-lg text-xs font-medium transition-all active:scale-95"
            title="Refresh Dashboard Feed"
          >
            <RefreshCw
              size={13}
              className={`text-primary ${isRefreshing || postsFetching ? 'animate-spin' : ''}`}
            />
            <span>Refresh</span>
          </button>

          {/* Upload Video Primary CTA */}
          <button
            onClick={() => navigate('/upload')}
            className="h-8 flex items-center gap-2 px-3.5 bg-primary hover:bg-primary-hover text-white font-semibold text-xs rounded-lg shadow-sm active:scale-95 transition-all"
          >
            <Upload size={14} />
            <span>Upload Video</span>
          </button>

          {/* Vertical Divider */}
          <div className="h-4 w-px bg-border-subtle mx-0.5" />

          {/* System Actions */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => navigate('/failed')}
              className="w-8 h-8 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-2 rounded-lg transition-colors relative"
              title="Notifications / Failed alerts"
            >
              <Bell size={16} />
              {failedCount > 0 && (
                <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-status-danger" />
              )}
            </button>
            <button
              onClick={() => navigate('/channels')}
              className="w-8 h-8 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-2 rounded-lg transition-colors"
              title="Channels & Settings"
            >
              <Settings size={16} />
            </button>
          </div>
        </div>
      </header>

      {/* ===================================================================== */}
      {/* MAIN WORKSPACE CANVAS                                                  */}
      {/* ===================================================================== */}
      <main className="p-6 space-y-6 max-w-[1680px] w-full mx-auto">
        {/* Reset Feedback Notification */}
        {resetMsg && (
          <div className="p-3 bg-surface-2 border border-[#3B82F6]/40 rounded-xl text-xs text-primary flex items-center gap-2 animate-in fade-in">
            <Check size={14} className="text-status-success" />
            <span>{resetMsg}</span>
          </div>
        )}

        {/* Active Running Job Banner */}
        <RunningJobBanner runningPost={runningJobData} queuedCount={queuedCount} />

        {/* =================================================================== */}
        {/* SECTION A: METRIC & TELEMETRY KPI TILES                             */}
        {/* =================================================================== */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {/* Metric 1: TOTAL POSTS */}
          <div className="bg-surface-1 border border-border-subtle p-4 rounded-xl relative overflow-hidden group hover:border-border-strong transition-all flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between h-5">
                <span className="text-label-caps text-outline uppercase tracking-wider text-[11px]">Total Posts</span>
                <Layers size={16} className="text-outline group-hover:text-primary transition-colors" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-display-lg text-on-surface">{totalCount}</span>
                <span className="text-mono-data-sm text-status-success text-xs flex items-center">
                  ↑ active
                </span>
              </div>
            </div>
            <div className="mt-2 h-6 flex items-center text-mono-data-sm text-outline text-[11px]">
              Across {channels.length || 3} active channels
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-primary to-transparent opacity-50" />
          </div>

          {/* Metric 2: IN PIPELINE */}
          <div className="bg-surface-1 border border-border-subtle p-4 rounded-xl relative overflow-hidden group hover:border-border-strong transition-all flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between h-5">
                <span className="text-label-caps text-outline uppercase tracking-wider text-[11px]">In Pipeline</span>
                <Hourglass size={16} className="text-outline group-hover:text-status-info transition-colors" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-display-lg text-on-surface">{inPipelineCount}</span>
                <span className="text-mono-data-sm text-outline text-xs">
                  {inPipelineCount > 0 ? 'Processing' : 'Idle'}
                </span>
              </div>
            </div>
            <div className="mt-2 h-6 flex items-center text-mono-data-sm text-outline text-[11px]">
              {inPipelineCount > 0 ? `${queuedCount} queued in transcoder` : 'Transcoder queue clear'}
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-outline to-transparent opacity-20" />
          </div>

          {/* Metric 3: SCHEDULED */}
          <div className="bg-surface-1 border border-border-subtle p-4 rounded-xl relative overflow-hidden group hover:border-border-strong transition-all flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between h-5">
                <span className="text-label-caps text-outline uppercase tracking-wider text-[11px]">Scheduled</span>
                <Calendar size={16} className="text-status-warning" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-display-lg text-on-surface">{scheduledCount}</span>
                <span className="text-mono-data-sm text-status-warning bg-status-warning/10 px-1.5 py-0.5 rounded border border-status-warning/20 text-[10px]">
                  Ready to Publish
                </span>
              </div>
            </div>
            <div className="mt-2 h-6 flex items-center text-mono-data-sm text-outline text-[11px]">
              Automated stagger release
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-[#F59E0B] to-transparent opacity-40" />
          </div>

          {/* Metric 4: DONE (COMMENTED) */}
          <div className="bg-surface-1 border border-border-subtle p-4 rounded-xl relative overflow-hidden group hover:border-border-strong transition-all flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between h-5">
                <span className="text-label-caps text-outline uppercase tracking-wider text-[11px]">Done (Commented)</span>
                <CheckCircle2 size={16} className="text-status-success" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-display-lg text-on-surface">{completedCount}</span>
                <span className="text-mono-data-sm text-status-success bg-status-success/10 px-1.5 py-0.5 rounded border border-status-success/20 text-[10px]">
                  100% verified
                </span>
              </div>
            </div>
            <div className="mt-2 h-6 flex items-center text-mono-data-sm text-outline text-[11px]">
              First-comment pinned
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-[#10B981] to-transparent opacity-40" />
          </div>

          {/* Metric 5: ACTION REQUIRED / FAILED */}
          <div
            className={`p-4 rounded-xl relative overflow-hidden group transition-all flex flex-col justify-between ${
              failedCount > 0
                ? 'bg-status-danger/5 border border-status-danger/30 hover:border-status-danger/60'
                : 'bg-surface-1 border border-border-subtle hover:border-border-strong'
            }`}
          >
            <div>
              <div className="flex items-center justify-between h-5">
                <span className={`text-label-caps uppercase tracking-wider text-[11px] font-bold ${failedCount > 0 ? 'text-status-danger' : 'text-outline'}`}>
                  {failedCount > 0 ? 'Action Required' : 'Failed Jobs'}
                </span>
                <AlertTriangle
                  size={16}
                  className={failedCount > 0 ? 'text-status-danger animate-pulse' : 'text-outline'}
                />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className={`text-display-lg font-bold ${failedCount > 0 ? 'text-status-danger' : 'text-on-surface'}`}>
                  {failedCount}
                </span>
                <span className={`text-mono-data-sm text-xs ${failedCount > 0 ? 'text-status-danger' : 'text-outline'}`}>
                  FAILED
                </span>
              </div>
            </div>
            <div className="mt-2 h-6 flex items-center justify-between text-mono-data-sm text-[11px]">
              <span className="text-outline truncate">
                {failedCount > 0 ? 'Watermark / limits' : 'All pipelines clean'}
              </span>
              {failedCount > 0 && (
                <button
                  onClick={() => setStatus('failed')}
                  className="shrink-0 text-mono-data-sm text-white bg-status-danger/20 hover:bg-status-danger/40 border border-status-danger/40 px-2 py-0.5 rounded text-[10px] transition-all ml-1.5"
                >
                  Inspect →
                </button>
              )}
            </div>
            {failedCount > 0 && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#F43F5E]" />
            )}
          </div>
        </section>

        {/* =================================================================== */}
        {/* SECTION B: ADVANCED FILTERING & SEGMENT CONTROL BAR                 */}
        {/* =================================================================== */}
        <section className="bg-surface-1 border border-border-subtle rounded-xl p-3.5 space-y-3">
          {/* Channel Segment Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-border-subtle">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="w-16 shrink-0 text-label-caps text-outline uppercase tracking-wider text-[11px] pl-1">
                Channel:
              </span>
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  onClick={() => setChannel('all')}
                  className={`px-3 py-1.5 text-mono-data-sm text-xs rounded-lg transition-all ${
                    channel === 'all'
                      ? 'bg-surface-3 text-primary border border-primary/40 shadow-sm font-semibold'
                      : 'bg-surface-2 border border-border-subtle text-on-surface-variant hover:text-on-surface hover:bg-surface-3 hover:border-border-strong'
                  }`}
                >
                  All ({totalCount})
                </button>

                {channels.map(c => {
                  const count = channelCounts[c.channel] || 0
                  const isSelected = channel === c.channel
                  return (
                    <button
                      key={c.channel}
                      onClick={() => setChannel(c.channel)}
                      className={`px-3 py-1.5 text-mono-data-sm text-xs rounded-lg transition-all ${
                        isSelected
                          ? 'bg-surface-3 text-primary border border-primary/40 shadow-sm font-semibold'
                          : 'bg-surface-2 border border-border-subtle text-on-surface-variant hover:text-on-surface hover:bg-surface-3 hover:border-border-strong'
                      }`}
                    >
                      {c.display_name || c.channel} ({count})
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Quick Bulk Actions */}
            <div className="flex items-center gap-2 ml-auto">
              <button
                onClick={exportCSV}
                className="flex items-center gap-1.5 px-3 py-1.5 text-mono-data-sm text-xs bg-surface-2 border border-border-subtle text-on-surface-variant hover:text-on-surface hover:border-border-strong rounded-lg transition-all"
                title="Export visible posts to CSV"
              >
                <Download size={13} />
                <span>Export CSV</span>
              </button>

              {stuckCount > 0 && (
                <button
                  onClick={handleResetStuck}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-mono-data-sm text-xs bg-status-warning/10 border border-status-warning/30 text-status-warning hover:bg-status-warning/20 rounded-lg transition-all"
                  title="Bulk retry stuck jobs"
                >
                  <RotateCcw size={13} />
                  <span>Bulk Retry ({stuckCount})</span>
                </button>
              )}
            </div>
          </div>

          {/* Status Filter Chips Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="w-16 shrink-0 text-label-caps text-outline uppercase tracking-wider text-[11px] pl-1">
                Status:
              </span>
              <div className="flex flex-wrap items-center gap-1.5">
                {STATUSES.map(s => {
                  const isSelected = status === s.id
                  let extraBadge = null
                  if (s.id === 'scheduled' && scheduledCount > 0) extraBadge = ` (${scheduledCount})`
                  if (s.id === 'commented' && completedCount > 0) extraBadge = ` (${completedCount})`
                  if (s.id === 'failed' && failedCount > 0) extraBadge = ` (${failedCount})`

                  return (
                    <button
                      key={s.id}
                      onClick={() => setStatus(s.id)}
                      className={`px-3 py-1 text-mono-data-sm text-xs rounded-lg transition-all flex items-center gap-1.5 ${
                        isSelected
                          ? 'bg-surface-3 text-on-surface border border-primary font-semibold ring-1 ring-primary/40 shadow-sm'
                          : s.id === 'failed' && failedCount > 0
                          ? 'bg-status-danger/10 border border-status-danger/30 text-status-danger hover:bg-status-danger/20'
                          : 'bg-surface-2 border border-border-subtle text-outline hover:text-on-surface hover:bg-surface-3 hover:border-border-strong'
                      }`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
                      <span>{s.label}{extraBadge}</span>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Telemetry Date Pill */}
            <div className="flex items-center gap-1.5 text-mono-data-sm text-outline text-xs ml-auto">
              <Calendar size={13} />
              <span>Production Pipeline Sync</span>
            </div>
          </div>
        </section>

        {/* =================================================================== */}
        {/* SECTION C: ENTERPRISE DATA TABLE (Exact Schema Parity)               */}
        {/* =================================================================== */}
        <section className="bg-surface-1 border border-border-subtle rounded-xl overflow-hidden shadow-2xl">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[900px]">
              <thead>
                <tr className="border-b border-border-subtle bg-surface-base/60 text-label-caps text-outline uppercase tracking-wider text-[11px]">
                  <th className="py-3 px-4 w-16 text-left">ID</th>
                  <th className="py-3 px-4">Post Title &amp; Pipeline Metadata</th>
                  <th className="py-3 px-4 w-44 text-left">Channel</th>
                  <th className="py-3 px-4 w-48 text-left">Status &amp; Timing</th>
                  <th className="py-3 px-4 w-40 text-left">Scheduled Time</th>
                  <th className="py-3 px-4 w-36 text-left">YouTube Link</th>
                  <th className="py-3 px-4 w-20 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle/60 text-xs">
                {/* Initial Loading Skeleton */}
                {isInitialLoad && (
                  <tr>
                    <td colSpan={7} className="p-8">
                      <div className="space-y-3">
                        <div className="h-6 bg-surface-2 rounded animate-pulse w-full" />
                        <div className="h-6 bg-surface-2 rounded animate-pulse w-5/6" />
                        <div className="h-6 bg-surface-2 rounded animate-pulse w-4/6" />
                      </div>
                    </td>
                  </tr>
                )}

                {/* Empty State */}
                {!isInitialLoad && posts.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-12 text-center">
                      <div className="flex flex-col items-center justify-center gap-2">
                        <div className="w-10 h-10 rounded-full bg-surface-2 border border-border-subtle flex items-center justify-center text-outline">
                          <Layers size={18} />
                        </div>
                        <p className="font-semibold text-on-surface text-sm">No posts found</p>
                        <p className="text-xs text-outline max-w-sm">
                          {status !== 'all' || channel !== 'all' || searchQuery
                            ? 'No posts match your current search and filter criteria.'
                            : 'Upload a video to begin the automated watermark removal and publishing workflow.'}
                        </p>
                        <button
                          onClick={() => navigate('/upload')}
                          className="mt-2 flex items-center gap-1.5 px-3 py-1.5 bg-[#3B82F6] text-white text-xs font-semibold rounded-lg shadow-sm"
                        >
                          <Upload size={13} />
                          <span>Upload New Video</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                )}

                {/* Post Rows */}
                {posts.map(p => {
                  const channelLabel = p.channel_display_name || p.channel?.replace(/_/g, ' ') || 'Default'
                  const isFailed = p.status === 'failed'
                  const isCommented = p.status === 'commented'

                  return (
                    <tr
                      key={p.id}
                      onClick={() => navigate(`/post/${p.id}`)}
                      className={`hover:bg-surface-2 transition-colors duration-150 cursor-pointer group ${
                        isFailed ? 'bg-status-danger/[0.03] border-l-2 border-l-[#F43F5E]' : ''
                      } ${isCommented ? 'bg-status-success/[0.02]' : ''}`}
                    >
                      {/* ID */}
                      <td className="py-3 px-4 w-16 text-left font-mono text-outline group-hover:text-primary align-middle">
                        #{p.id}
                      </td>

                      {/* Title & Metadata */}
                      <td className="py-3 px-4 align-middle">
                        <div className="font-semibold text-on-surface group-hover:text-primary transition-colors line-clamp-1">
                          {p.enriched_title || p.title}
                        </div>
                        {p.title && p.enriched_title && (
                          <div className="text-mono-data-sm text-outline flex items-center gap-1 mt-0.5 text-[11px]">
                            <span className="text-outline/70">orig:</span> {p.title}
                          </div>
                        )}
                        {isFailed && p.error_message && (
                          <div className="text-mono-data-sm text-status-danger flex items-center gap-1 mt-0.5 text-[11px]">
                            <AlertCircle size={12} />
                            <span className="truncate max-w-md">{p.error_message}</span>
                          </div>
                        )}
                      </td>

                      {/* Channel */}
                      <td className="py-3 px-4 w-44 align-middle">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-surface-2 border border-border-strong text-mono-data-sm text-on-surface text-[11px]">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                          {channelLabel}
                        </span>
                      </td>

                      {/* Status & Timing */}
                      <td className="py-3 px-4 w-48 align-middle">
                        <StatusBadge status={p.status} post={p} showTiming />
                      </td>

                      {/* Scheduled Time */}
                      <td className="py-3 px-4 w-40 font-mono text-on-surface-variant text-[11px] align-middle">
                        {fmtTime(p.scheduled_at)}
                      </td>

                      {/* YouTube Link */}
                      <td className="py-3 px-4 w-36 align-middle" onClick={e => e.stopPropagation()}>
                        {p.youtube_video_id ? (
                          <a
                            href={`https://youtu.be/${p.youtube_video_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 font-mono text-primary hover:underline text-[11px]"
                          >
                            <span>{p.youtube_video_id}</span>
                            <ExternalLink size={12} />
                          </a>
                        ) : (
                          <span className="text-outline font-mono">—</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-3 px-4 w-20 text-right align-middle" onClick={e => e.stopPropagation()}>
                        {isFailed ? (
                          <button
                            onClick={() => navigate(`/post/${p.id}`)}
                            className="px-2 py-0.5 bg-status-danger/20 hover:bg-status-danger/30 text-status-danger border border-status-danger/40 rounded text-mono-data-sm text-[11px] transition-all"
                            title="Inspect & Retry"
                          >
                            Retry
                          </button>
                        ) : (
                          <button
                            onClick={() => navigate(`/post/${p.id}`)}
                            className="p-1 hover:bg-surface-3 rounded text-outline hover:text-on-surface transition-colors"
                            title="View post details"
                          >
                            <ChevronRight size={15} />
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Table Footer / Telemetry Bar */}
          <div className="px-4 py-3 bg-surface-base/80 border-t border-border-subtle flex flex-wrap items-center justify-between gap-4 text-mono-data-sm text-xs">
            <div className="flex items-center gap-3 text-outline">
              <span>
                Showing <strong className="text-on-surface font-semibold">{posts.length}</strong> of{' '}
                <strong className="text-on-surface font-semibold">{total}</strong> posts
              </span>
              <span className="text-border-strong">•</span>
              <span>Batch Engine #940-prod</span>
            </div>

            <div className="flex items-center gap-3">
              <span className="inline-flex items-center gap-1.5 text-on-surface-variant text-[11px]">
                <span className="w-2 h-2 rounded-full bg-status-success animate-ping" />
                Auto-refreshing (15s)
              </span>
            </div>
          </div>
        </section>

        {/* =================================================================== */}
        {/* SECTION D: PIPELINE DIAGNOSTIC INSPECTOR & TARGET CHANNELS         */}
        {/* =================================================================== */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Active Topology Graph */}
          <div className="lg:col-span-2 bg-surface-1 border border-border-subtle rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-border-subtle pb-3">
              <div className="flex items-center gap-2">
                <Terminal size={18} className="text-primary" />
                <h3 className="font-semibold text-sm text-on-surface">Active Pipeline Topology Graph</h3>
              </div>
              <span className="text-mono-data-sm text-status-success bg-status-success/10 px-2 py-0.5 rounded border border-status-success/20 text-[11px]">
                Deterministic 5-Step Model
              </span>
            </div>

            {/* Connected Step Nodes Visual Flow */}
            <div className="grid grid-cols-1 sm:grid-cols-5 gap-2.5 pt-1">
              {/* Step 1 */}
              <div className="p-3 rounded-lg bg-surface-2 border border-status-success/40 space-y-1">
                <div className="flex items-center justify-between text-mono-data-sm text-[10px]">
                  <span className="text-outline">01. INGEST</span>
                  <Check size={13} className="text-status-success" />
                </div>
                <p className="text-xs text-on-surface font-semibold">Raw Video In</p>
                <div className="text-mono-data-sm text-outline text-[10px]">Local / Ingest Dir</div>
              </div>

              {/* Step 2 */}
              <div className="p-3 rounded-lg bg-surface-2 border border-status-success/40 space-y-1">
                <div className="flex items-center justify-between text-mono-data-sm text-[10px]">
                  <span className="text-outline">02. CLEAN</span>
                  <Check size={13} className="text-status-success" />
                </div>
                <p className="text-xs text-on-surface font-semibold">Watermark Off</p>
                <div className="text-mono-data-sm text-outline text-[10px]">SSH Transcoder</div>
              </div>

              {/* Step 3 */}
              <div className="p-3 rounded-lg bg-surface-2 border border-status-success/40 space-y-1">
                <div className="flex items-center justify-between text-mono-data-sm text-[10px]">
                  <span className="text-outline">03. ENRICH</span>
                  <Check size={13} className="text-status-success" />
                </div>
                <p className="text-xs text-on-surface font-semibold">Gemini AI</p>
                <div className="text-mono-data-sm text-outline text-[10px]">SEO Titles &amp; Tags</div>
              </div>

              {/* Step 4 */}
              <div className="p-3 rounded-lg bg-surface-2 border border-primary/50 space-y-1 relative ring-1 ring-primary/20 shadow-sm">
                <div className="flex items-center justify-between text-mono-data-sm text-[10px]">
                  <span className="text-primary font-bold">04. TIMING</span>
                  <RefreshCw size={12} className="text-primary animate-spin" />
                </div>
                <p className="text-xs text-on-surface font-semibold">APScheduler</p>
                <div className="text-mono-data-sm text-primary text-[10px]">Stagger: 1 Post/Run</div>
              </div>

              {/* Step 5 */}
              <div className="p-3 rounded-lg bg-surface-base border border-dashed border-border-strong space-y-1 opacity-80">
                <div className="flex items-center justify-between text-mono-data-sm text-[10px]">
                  <span className="text-outline">05. PUBLISH</span>
                  <Calendar size={13} className="text-outline" />
                </div>
                <p className="text-xs text-outline font-semibold">YouTube v3</p>
                <div className="text-mono-data-sm text-outline text-[10px]">Auto-Pin Comment</div>
              </div>
            </div>

            {/* Live Daemon Log Console Trace */}
            <div className="bg-surface-base rounded-lg p-3 border border-border-subtle font-mono text-[11px] space-y-1 text-outline">
              <div className="flex items-center justify-between text-[10px] text-outline border-b border-border-subtle/40 pb-1 mb-1">
                <span>DAEMON TELEMETRY STREAM</span>
                <span className="text-status-success">PORT 8000 LIVE</span>
              </div>
              <div className="text-on-surface-variant">
                <span className="text-outline">[STATUS]</span>{' '}
                <span className="text-status-info">QUEUE:</span> Serial queue active •{' '}
                {inPipelineCount} in pipeline, {scheduledCount} scheduled.
              </div>
              <div className="text-on-surface-variant">
                <span className="text-outline">[SCHEDULER]</span>{' '}
                <span className="text-status-success">SUCCESS:</span> APScheduler cron running in background thread.
              </div>
              {failedCount > 0 && (
                <div className="text-status-danger">
                  <span className="text-outline">[ALERTS]</span>{' '}
                  <span className="font-bold">WARN:</span> {failedCount} job(s) in failed status. Click Inspect to review.
                </div>
              )}
            </div>
          </div>

          {/* Target Channels Matrix Card */}
          <div className="bg-surface-1 border border-border-subtle rounded-xl p-5 space-y-4 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between border-b border-border-subtle pb-3">
                <div className="flex items-center gap-2">
                  <Tv2 size={18} className="text-primary" />
                  <h3 className="font-semibold text-sm text-on-surface">Target Channels</h3>
                </div>
                <span className="text-mono-data-sm text-outline text-xs">
                  {channels.length} Configured
                </span>
              </div>

              <div className="mt-4 space-y-2.5">
                {channels.map(c => {
                  const count = channelCounts[c.channel] || 0
                  const initials = (c.display_name || c.channel || 'CH')
                    .split(' ')
                    .map(w => w[0])
                    .slice(0, 2)
                    .join('')
                    .toUpperCase()

                  return (
                    <div
                      key={c.channel}
                      onClick={() => setChannel(c.channel)}
                      className="flex items-center justify-between p-2.5 rounded-lg bg-surface-2 border border-border-subtle hover:border-primary/40 cursor-pointer transition-all"
                    >
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-lg bg-primary/10 text-primary flex items-center justify-center font-bold text-xs">
                          {initials}
                        </div>
                        <div>
                          <p className="text-xs text-on-surface font-semibold">
                            {c.display_name || c.channel}
                          </p>
                          <p className="text-mono-data-sm text-outline text-[10px]">
                            {count} posts • {c.upload_privacy || 'private'}
                          </p>
                        </div>
                      </div>
                      <span className="w-2 h-2 rounded-full bg-status-success" />
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="pt-3 border-t border-border-subtle">
              <button
                onClick={() => navigate('/channels')}
                className="w-full py-2 bg-surface-2 hover:bg-surface-3 border border-border-strong rounded-lg text-xs font-medium text-on-surface flex items-center justify-center gap-2 transition-all"
              >
                <Settings size={14} />
                <span>Manage Channels</span>
              </button>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}
