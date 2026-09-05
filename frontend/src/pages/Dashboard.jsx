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
  X,
} from 'lucide-react'
import StatusBadge from '../components/StatusBadge'
import RunningJobBanner from '../components/RunningJobBanner'
import { usePostsQuery, useRunningJobQuery, useResetStuck } from '../hooks/usePosts'
import { useChannelsQuery } from '../hooks/useChannels'
import { parseUTCDate } from '../utils/timeFormat'

const STATUSES = [
  { id: 'all',       label: 'All',       dotColor: 'bg-outline' },
  { id: 'queued',    label: 'Queued',    dotColor: 'bg-outline' },
  { id: 'cleaning',  label: 'Cleaning',  dotColor: 'bg-status-info' },
  { id: 'cleaned',   label: 'Cleaned',   dotColor: 'bg-status-info' },
  { id: 'scheduled', label: 'Scheduled', dotColor: 'bg-status-warning' },
  { id: 'commented', label: 'Commented', dotColor: 'bg-status-success' },
  { id: 'failed',    label: 'Failed',    dotColor: 'bg-status-danger' },
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
      {/* TOP HEADER                                                             */}
      {/* ===================================================================== */}
      <header className="sticky top-0 right-0 z-30 w-full px-6 flex justify-between items-center border-b border-border-subtle" style={{ height: 'var(--header-height)', backgroundColor: 'rgba(11,13,17,0.92)', backdropFilter: 'blur(8px)' }}>
        {/* Left: Page Title */}
        <div className="flex flex-col justify-center">
          <h2 className="font-semibold text-on-surface tracking-tight leading-tight" style={{ fontSize: 15 }}>
            Dashboard
          </h2>
          <p className="text-outline leading-tight mt-0.5 hidden sm:block" style={{ fontSize: 12 }}>
            Monitor your automated YouTube publishing pipeline
          </p>
        </div>

        {/* Right Controls */}
        <div className="flex items-center gap-2">
          {/* Search */}
          <div className="relative hidden md:block">
            <Search
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-outline pointer-events-none"
            />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search posts, IDs…"
              style={{ height: 30, width: 216, paddingLeft: 30, paddingRight: 36, fontSize: 12.5 }}
              className="bg-surface-1 border border-border-subtle rounded-md text-on-surface focus:outline-none focus:border-primary transition-all"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-outline pointer-events-none" style={{ fontSize: 10, backgroundColor: 'var(--bg-elevated)', padding: '1px 4px', borderRadius: 3, border: '1px solid var(--border-subtle)' }}>
              ⌘K
            </span>
          </div>

          {/* Reset Stuck — conditional */}
          {stuckCount > 0 && (
            <button
              onClick={handleResetStuck}
              className="h-8 flex items-center gap-1.5 px-2.5 bg-status-warning/10 border border-status-warning/25 text-status-warning hover:bg-status-warning/20 rounded-md text-xs font-medium transition-colors"
              title={`${stuckCount} stuck job(s) — click to re-queue`}
            >
              <RotateCcw size={12} />
              <span className="hidden sm:inline">Reset Stuck ({stuckCount})</span>
            </button>
          )}

          {/* Refresh */}
          <button
            onClick={handleRefresh}
            disabled={postsFetching}
            className="h-8 w-8 flex items-center justify-center bg-surface-1 border border-border-subtle text-on-surface-variant hover:text-on-surface hover:bg-surface-2 rounded-md transition-colors disabled:opacity-50"
            title="Refresh data"
          >
            <RefreshCw
              size={14}
              className={isRefreshing || postsFetching ? 'animate-spin' : ''}
            />
          </button>

          {/* Upload Video — Primary CTA */}
          <button
            onClick={() => navigate('/upload')}
            className="btn btn-primary"
          >
            <Upload size={13} />
            <span>Upload Video</span>
          </button>

          {/* Divider */}
          <div className="h-5 w-px bg-border-subtle mx-0.5" />

          {/* Icon actions */}
          <button
            onClick={() => navigate('/failed')}
            className="w-8 h-8 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-1 rounded-md transition-colors relative"
            title="Failed jobs"
          >
            <Bell size={15} />
            {failedCount > 0 && (
              <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-status-danger" />
            )}
          </button>
          <button
            onClick={() => navigate('/channels')}
            className="w-8 h-8 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-1 rounded-md transition-colors"
            title="Channels & settings"
          >
            <Settings size={15} />
          </button>
        </div>
      </header>

      {/* ===================================================================== */}
      {/* MAIN CONTENT                                                           */}
      {/* ===================================================================== */}
      <main className="flex flex-col gap-5 w-full mx-auto" style={{ padding: '24px 24px 56px', maxWidth: 'var(--content-max-w)' }}>

        {/* Reset feedback notification */}
        {resetMsg && (
          <div className="flex items-center gap-2 px-4 py-2.5 bg-surface-1 border border-border-strong rounded-lg text-xs text-on-surface animate-in fade-in">
            <Check size={13} className="text-status-success shrink-0" />
            <span>{resetMsg}</span>
          </div>
        )}

        {/* Running job banner */}
        <RunningJobBanner runningPost={runningJobData} queuedCount={queuedCount} />

        {/* ================================================================= */}
        {/* SECTION A: STAT CARDS                                              */}
        {/* ================================================================= */}
        <section className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>

          {/* Total Posts */}
          <StatCard
            label="Total Posts"
            value={totalCount}
            sub={`${channels.length || 0} active channel${channels.length !== 1 ? 's' : ''}`}
            icon={<Layers size={14} />}
            accent="default"
          />

          {/* In Pipeline */}
          <StatCard
            label="In Pipeline"
            value={inPipelineCount}
            sub={inPipelineCount > 0 ? `${queuedCount} queued` : 'Queue clear'}
            icon={<Hourglass size={14} />}
            accent="info"
          />

          {/* Scheduled */}
          <StatCard
            label="Scheduled"
            value={scheduledCount}
            sub="Ready to publish"
            icon={<Calendar size={14} />}
            accent="warning"
          />

          {/* Commented / Done */}
          <StatCard
            label="Completed"
            value={completedCount}
            sub="First comment pinned"
            icon={<CheckCircle2 size={14} />}
            accent="success"
          />

          {/* Failed */}
          <StatCard
            label={failedCount > 0 ? 'Action Required' : 'Failed'}
            value={failedCount}
            sub={failedCount > 0 ? 'Needs attention' : 'All pipelines clean'}
            icon={<AlertTriangle size={14} />}
            accent={failedCount > 0 ? 'danger' : 'default'}
            actionLabel={failedCount > 0 ? 'Inspect' : null}
            onAction={failedCount > 0 ? () => setStatus('failed') : null}
          />
        </section>

        {/* ================================================================= */}
        {/* SECTION B: FILTER TOOLBAR                                          */}
        {/* ================================================================= */}
        <section style={{ backgroundColor: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
          {/* Channel row */}
          <div className="flex flex-wrap items-center gap-3 px-5 py-4 border-b border-border-subtle">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-outline w-14 shrink-0">
              Channel
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <FilterChip
                active={channel === 'all'}
                onClick={() => setChannel('all')}
                label={`All (${totalCount})`}
              />
              {channels.map(c => (
                <FilterChip
                  key={c.channel}
                  active={channel === c.channel}
                  onClick={() => setChannel(c.channel)}
                  label={`${c.display_name || c.channel} (${channelCounts[c.channel] || 0})`}
                />
              ))}
            </div>
            {/* Export CSV + Bulk Retry pushed right */}
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={exportCSV}
                className="flex items-center gap-1.5 h-8 px-3 text-[11px] bg-surface-2 border border-border-subtle text-on-surface-variant hover:text-on-surface hover:border-border-strong rounded-md transition-colors font-medium"
                title="Export visible posts to CSV"
              >
                <Download size={13} />
                <span>Export CSV</span>
              </button>
              {failedCount > 0 && (
                <button
                  onClick={handleResetStuck}
                  className="flex items-center gap-1.5 h-8 px-3 text-[11px] bg-status-danger/10 border border-status-danger/25 text-status-danger hover:bg-status-danger/20 rounded-md transition-colors font-medium"
                  title="Re-queue all stuck/failed jobs"
                >
                  <RotateCcw size={12} />
                  <span>Bulk Retry ({failedCount})</span>
                </button>
              )}
            </div>
          </div>

          {/* Status row */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-outline w-14 shrink-0">
                Status
              </span>
              <div className="flex flex-wrap items-center gap-2">
                {STATUSES.map(s => {
                  const isSelected = status === s.id
                  const isFailed = s.id === 'failed'
                  const count = s.id === 'scheduled' ? scheduledCount
                    : s.id === 'commented' ? completedCount
                    : s.id === 'failed' ? failedCount
                    : null
                  return (
                    <button
                      key={s.id}
                      onClick={() => setStatus(s.id)}
                      className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11px] font-medium transition-colors border ${
                        isSelected
                          ? 'bg-surface-3 text-on-surface border-border-strong'
                          : isFailed && failedCount > 0
                          ? 'bg-status-danger/8 border-status-danger/25 text-status-danger hover:bg-status-danger/15'
                          : 'bg-surface-2 border-border-subtle text-outline hover:text-on-surface hover:border-border-strong hover:bg-surface-3'
                      }`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${s.dotColor}`} />
                      <span>{s.label}{count != null && count > 0 ? ` (${count})` : ''}</span>
                    </button>
                  )
                })}
              </div>
            </div>
            {/* Date range */}
            <div className="flex items-center gap-1.5 text-[11px] font-mono text-outline">
              <Calendar size={12} />
              <span>{new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })} – {new Date().toLocaleDateString('en-IN', { month: 'short', day: 'numeric', year: 'numeric' })}</span>
            </div>
          </div>
        </section>

        {/* ================================================================= */}
        {/* SECTION C: POSTS TABLE                                             */}
        {/* ================================================================= */}
        <section style={{ backgroundColor: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 8, overflow: 'hidden' }}>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse" style={{ minWidth: 860 }}>
              <thead>
                <tr className="border-b border-border-subtle bg-surface-base/40">
                  <th className="py-3.5 px-5 text-[10px] font-semibold uppercase tracking-wider text-outline w-14 text-left">ID</th>
                  <th className="py-3.5 px-5 text-[10px] font-semibold uppercase tracking-wider text-outline text-left">Post / Title</th>
                  <th className="py-3.5 px-5 text-[10px] font-semibold uppercase tracking-wider text-outline w-36 text-left">Channel</th>
                  <th className="py-3.5 px-5 text-[10px] font-semibold uppercase tracking-wider text-outline w-36 text-left">Status</th>
                  <th className="py-3.5 px-5 text-[10px] font-semibold uppercase tracking-wider text-outline w-36 text-left">Scheduled</th>
                  <th className="py-3.5 px-5 text-[10px] font-semibold uppercase tracking-wider text-outline w-24 text-left">YouTube</th>
                  <th className="py-3.5 px-5 text-[10px] font-semibold uppercase tracking-wider text-outline w-16 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle/50">

                {/* Loading skeleton */}
                {isInitialLoad && (
                  <tr>
                    <td colSpan={7} className="p-8">
                      <div className="flex flex-col gap-3">
                        {[...Array(4)].map((_, i) => (
                          <div key={i} className="h-5 bg-surface-2 rounded animate-pulse" style={{ width: `${90 - i * 8}%` }} />
                        ))}
                      </div>
                    </td>
                  </tr>
                )}

                {/* Empty state */}
                {!isInitialLoad && posts.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-16 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-surface-2 border border-border-subtle flex items-center justify-center text-outline">
                          <Layers size={16} />
                        </div>
                        <div>
                          <p className="text-sm font-semibold text-on-surface mb-1">No posts found</p>
                          <p className="text-xs text-outline max-w-xs">
                            {status !== 'all' || channel !== 'all' || searchQuery
                              ? 'No posts match your current filters.'
                              : 'Upload a video to begin the automated publishing workflow.'}
                          </p>
                        </div>
                        <button
                          onClick={() => navigate('/upload')}
                          className="mt-1 flex items-center gap-1.5 h-8 px-3 bg-primary hover:bg-primary-hover text-white text-xs font-semibold rounded-md shadow-sm transition-colors"
                        >
                          <Upload size={13} />
                          <span>Upload Video</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                )}

                {/* Post rows */}
                {posts.map(p => {
                  const channelLabel = p.channel_display_name || p.channel?.replace(/_/g, ' ') || 'Default'
                  const isFailed = p.status === 'failed'
                  const isCommented = p.status === 'commented'

                  return (
                    <tr
                      key={p.id}
                      onClick={() => navigate(`/post/${p.id}`)}
                      className={`transition-colors duration-150 cursor-pointer group hover:bg-surface-2/60 ${
                        isFailed ? 'border-l-2 border-l-status-danger bg-status-danger/[0.02]' : ''
                      } ${isCommented ? 'bg-status-success/[0.015]' : ''}`}
                    >
                      {/* ID */}
                      <td className="py-4 px-5 w-14 align-middle">
                        <span className="font-mono text-[11px] text-outline group-hover:text-primary transition-colors">
                          #{p.id}
                        </span>
                      </td>

                      {/* Title */}
                      <td className="py-4 px-5 align-middle max-w-0">
                        <div className="truncate font-medium text-[13px] text-on-surface group-hover:text-primary transition-colors">
                          {p.enriched_title || p.title}
                        </div>
                        {p.title && p.enriched_title && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <span className="text-[11px] text-outline/60 font-mono">orig:</span>
                            <span className="truncate text-[11px] text-outline">{p.title}</span>
                          </div>
                        )}
                        {isFailed && p.error_message && (
                          <div className="flex items-center gap-1 mt-0.5">
                            <AlertCircle size={10} className="text-status-danger shrink-0" />
                            <span className="truncate text-[11px] text-status-danger">{p.error_message}</span>
                          </div>
                        )}
                      </td>

                      {/* Channel */}
                      <td className="py-4 px-5 w-36 align-middle">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-surface-2 border border-border-strong text-[11px] text-on-surface-variant font-medium max-w-full truncate">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
                          <span className="truncate">{channelLabel}</span>
                        </span>
                      </td>

                      {/* Status */}
                      <td className="py-4 px-5 w-36 align-middle">
                        <StatusBadge status={p.status} post={p} showTiming />
                      </td>

                      {/* Scheduled time */}
                      <td className="py-4 px-5 w-36 align-middle">
                        <span className="font-mono text-[11px] text-on-surface-variant">
                          {fmtTime(p.scheduled_at)}
                        </span>
                      </td>

                      {/* YouTube link */}
                      <td className="py-4 px-5 w-24 align-middle" onClick={e => e.stopPropagation()}>
                        {p.youtube_video_id ? (
                          <a
                            href={`https://youtu.be/${p.youtube_video_id}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-[11px] text-primary hover:text-primary-hover font-medium transition-colors"
                            title={`Open youtube.com/watch?v=${p.youtube_video_id}`}
                          >
                            <span>Open</span>
                            <ExternalLink size={10} />
                          </a>
                        ) : (
                          <span className="text-outline font-mono text-[11px]">—</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="py-4 px-5 w-16 text-right align-middle" onClick={e => e.stopPropagation()}>
                        {isFailed ? (
                          <button
                            onClick={() => navigate(`/post/${p.id}`)}
                            className="inline-flex items-center gap-1 h-7 px-2 bg-status-danger/15 hover:bg-status-danger/25 text-status-danger border border-status-danger/30 rounded text-[11px] font-medium transition-colors"
                            title="Inspect & retry"
                          >
                            <RotateCcw size={10} />
                            <span>Retry</span>
                          </button>
                        ) : (
                          <button
                            onClick={() => navigate(`/post/${p.id}`)}
                            className="w-7 h-7 flex items-center justify-center ml-auto hover:bg-surface-3 rounded text-outline hover:text-on-surface transition-colors opacity-0 group-hover:opacity-100"
                            title="View details"
                          >
                            <ChevronRight size={14} />
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Table footer */}
          <div className="px-5 py-3.5 border-t border-border-subtle bg-surface-base/40 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3 text-[11px] text-outline">
              <span>
                Showing <strong className="text-on-surface font-semibold">{posts.length}</strong> of{' '}
                <strong className="text-on-surface font-semibold">{total}</strong> posts
              </span>
              <span className="text-border-strong">·</span>
              <span>Batch Engine #940-prod</span>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5 text-[11px] text-outline">
                <span className="w-1.5 h-1.5 rounded-full bg-status-success animate-pulse" />
                <span>Auto-refreshing · 15s</span>
              </div>
              {/* Pagination */}
              <div className="flex items-center gap-1">
                <button
                  className="w-6 h-6 flex items-center justify-center rounded bg-surface-2 border border-border-subtle text-outline opacity-40 cursor-not-allowed"
                  disabled
                >
                  <ChevronLeft size={13} />
                </button>
                <span className="px-2 h-6 flex items-center text-[11px] font-mono text-primary bg-surface-2 border border-border-strong rounded">
                  1
                </span>
                <button
                  className="w-6 h-6 flex items-center justify-center rounded bg-surface-2 border border-border-subtle text-on-surface-variant hover:bg-surface-3 hover:text-on-surface transition-colors"
                >
                  <ChevronRight size={13} />
                </button>
              </div>
            </div>
          </div>
        </section>

        {/* ================================================================= */}
        {/* SECTION D: PIPELINE + CHANNELS                                     */}
        {/* ================================================================= */}
        <section className="grid gap-5" style={{ gridTemplateColumns: '1fr 1fr 1fr' }}>

          {/* Pipeline stepper — spans 2 of 3 columns */}
          <div style={{ gridColumn: 'span 2', backgroundColor: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 24 }} className="flex flex-col">
            <div className="flex items-center justify-between mb-5 pb-4 border-b border-border-subtle">
              <div className="flex items-center gap-2">
                <Terminal size={15} className="text-primary" />
                <h3 className="font-semibold text-on-surface" style={{ fontSize: 13.5 }}>Active Pipeline Topology</h3>
              </div>
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--success)', backgroundColor: 'var(--success-subtle)', border: '1px solid var(--success-border)', padding: '2px 9px', borderRadius: 20 }}>
                Deterministic 5-Step Model
              </span>
            </div>

            {/* Steps */}
            <div className="grid grid-cols-5 gap-3">
              <PipelineStep num="01" label="Raw Video In" sub="Ingest" tech="Cloudflare R2" state="done" />
              <PipelineStep num="02" label="Watermark Off" sub="Clean" tech="CV Bounding Box" state="done" />
              <PipelineStep num="03" label="ASMR Enhance" sub="Enrich" tech="Gemini AI" state="done" />
              <PipelineStep num="04" label="Cron Schedule" sub="Timing" tech="APScheduler" state="active" />
              <PipelineStep num="05" label="YouTube API v3" sub="Publish" tech="Auto-Pin Comment" state="pending" />
            </div>

            {/* Status summary */}
            <div className="mt-6 pt-5 border-t border-border-subtle grid grid-cols-3 gap-4">
              <div className="flex flex-col items-center gap-1 p-3 rounded-lg bg-surface-2 border border-border-subtle">
                <div className="text-2xl font-bold text-on-surface tabular-nums">{inPipelineCount}</div>
                <div className="text-[10px] text-outline uppercase tracking-wider font-semibold">In Pipeline</div>
              </div>
              <div className="flex flex-col items-center gap-1 p-3 rounded-lg bg-status-warning/5 border border-status-warning/20">
                <div className="text-2xl font-bold text-status-warning tabular-nums">{scheduledCount}</div>
                <div className="text-[10px] text-outline uppercase tracking-wider font-semibold">Scheduled</div>
              </div>
              <div className={`flex flex-col items-center gap-1 p-3 rounded-lg border ${
                failedCount > 0
                  ? 'bg-status-danger/5 border-status-danger/20'
                  : 'bg-surface-2 border-border-subtle'
              }`}>
                <div className={`text-2xl font-bold tabular-nums ${failedCount > 0 ? 'text-status-danger' : 'text-on-surface'}`}>{failedCount}</div>
                <div className="text-[10px] text-outline uppercase tracking-wider font-semibold">Failed</div>
              </div>
            </div>

            {/* Daemon telemetry strip */}
            <div className="mt-4 p-3 rounded-lg bg-surface-base border border-border-subtle font-mono text-[11px] space-y-1.5">
              <div className="flex items-center justify-between text-[10px] text-outline border-b border-border-subtle/50 pb-1.5">
                <span className="uppercase tracking-wider">Daemon Telemetry Stream</span>
                <span className="text-status-success">Port 8092 Listening</span>
              </div>
              {resetMsg ? (
                <div className="truncate text-on-surface-variant">
                  <span className="text-outline">[{new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}]</span>{' '}
                  <span className="text-status-success">INFO:</span>{' '}
                  {resetMsg}
                </div>
              ) : failedCount > 0 ? (
                <div className="truncate text-on-surface-variant">
                  <span className="text-outline">[sys]</span>{' '}
                  <span className="text-status-warning">WARN:</span>{' '}
                  {failedCount} post{failedCount !== 1 ? 's' : ''} failed threshold test. Auto-retry available.
                </div>
              ) : (
                <div className="truncate text-outline">
                  <span>[sys]</span>{' '}
                  <span className="text-status-success">OK:</span>{' '}
                  All pipeline stages nominal. {scheduledCount} posts in publish queue.
                </div>
              )}
            </div>
          </div>

          {/* Target channels */}
          <div style={{ backgroundColor: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 24 }} className="flex flex-col">
            <div className="flex items-center justify-between pb-4 border-b border-border-subtle mb-4">
              <div className="flex items-center gap-2">
                <Tv2 size={15} className="text-primary" />
                <h3 className="text-sm font-semibold text-on-surface">Target Channels</h3>
              </div>
              <button
                onClick={() => navigate('/channels')}
                className="text-[11px] text-primary hover:underline font-medium"
              >
                Manage channels →
              </button>
            </div>

            <div className="flex flex-col gap-2.5 flex-1">
              {channels.length === 0 && (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <Tv2 size={20} className="text-outline mb-2" />
                  <p className="text-xs text-outline">No channels configured</p>
                </div>
              )}
              {channels.map(c => {
                const count = channelCounts[c.channel] || 0
                const failedForChannel = rawPosts.filter(p => p.channel === c.channel && p.status === 'failed').length
                const commentedForChannel = rawPosts.filter(p => p.channel === c.channel && p.status === 'commented').length
                const initials = (c.display_name || c.channel || 'CH')
                  .split(' ')
                  .map(w => w[0])
                  .slice(0, 2)
                  .join('')
                  .toUpperCase()

                return (
                  <button
                    key={c.channel}
                    onClick={() => setChannel(c.channel)}
                    className="flex items-center gap-3 p-3 rounded-lg bg-surface-2 border border-border-subtle hover:border-border-strong hover:bg-surface-3 transition-colors text-left group"
                  >
                    <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center font-bold text-xs shrink-0 border border-primary/15">
                      {initials}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-on-surface truncate">
                        {c.display_name || c.channel}
                      </p>
                      <p className={`text-[11px] mt-0.5 font-mono ${
                        failedForChannel > 0 ? 'text-status-danger' : 'text-outline'
                      }`}>
                        {failedForChannel > 0
                          ? `${failedForChannel} failed · token refresh req`
                          : `${count} posts queued · ${commentedForChannel} commented`}
                      </p>
                    </div>
                    <span className={`w-2 h-2 rounded-full shrink-0 ${
                      failedForChannel > 0 ? 'bg-status-danger' : 'bg-status-success'
                    }`} />
                  </button>
                )
              })}
            </div>

            <div className="mt-5 pt-4 border-t border-border-subtle">
              <button
                onClick={() => navigate('/channels')}
                className="w-full flex items-center justify-center gap-1.5 h-8 rounded-lg bg-surface-2 border border-border-subtle text-[11px] text-on-surface-variant hover:text-on-surface hover:border-border-strong hover:bg-surface-3 font-medium transition-colors"
              >
                <Activity size={12} />
                <span>+ Connect New Channel</span>
              </button>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

/* =========================================================================
   SUB-COMPONENTS (local, no state)
   ========================================================================= */

const ACCENT_MAP = {
  default: {
    icon: 'text-outline',
    value: 'text-on-surface',
    border: '',
    bg: '',
  },
  success: {
    icon: 'text-status-success',
    value: 'text-on-surface',
    border: '',
    bg: '',
  },
  warning: {
    icon: 'text-status-warning',
    value: 'text-on-surface',
    border: '',
    bg: '',
  },
  danger: {
    icon: 'text-status-danger',
    value: 'text-status-danger',
    border: 'border-status-danger/20',
    bg: 'bg-status-danger/[0.03]',
  },
  info: {
    icon: 'text-status-info',
    value: 'text-on-surface',
    border: '',
    bg: '',
  },
}

function StatCard({ label, value, sub, icon, accent = 'default', actionLabel, onAction }) {
  const bgMap = {
    default: 'var(--bg-elevated)',
    success: 'rgba(16,185,129,0.08)',
    warning: 'rgba(245,158,11,0.08)',
    danger:  'rgba(244,63,94,0.08)',
    info:    'rgba(2,132,199,0.08)',
  }
  const iconBgMap = {
    default: 'var(--bg-elevated)',
    success: 'rgba(16,185,129,0.12)',
    warning: 'rgba(245,158,11,0.12)',
    danger:  'rgba(244,63,94,0.12)',
    info:    'rgba(2,132,199,0.12)',
  }
  const iconColorMap = {
    default: 'var(--text-muted)',
    success: 'var(--success)',
    warning: 'var(--warning)',
    danger:  'var(--error)',
    info:    'var(--info)',
  }
  const valueColorMap = {
    default: 'var(--text-primary)',
    success: 'var(--text-primary)',
    warning: 'var(--text-primary)',
    danger:  'var(--error)',
    info:    'var(--text-primary)',
  }
  const borderMap = {
    default: 'var(--border-subtle)',
    success: 'var(--border-subtle)',
    warning: 'var(--border-subtle)',
    danger:  'rgba(244,63,94,0.2)',
    info:    'var(--border-subtle)',
  }
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 12,
      padding: '16px', borderRadius: 8,
      backgroundColor: bgMap[accent] || bgMap.default,
      border: `1px solid ${borderMap[accent] || borderMap.default}`,
      transition: 'border-color var(--transition-fast)',
    }}>
      <div className="flex items-center justify-between">
        <span style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>
          {label}
        </span>
        <div style={{
          width: 28, height: 28, borderRadius: 7,
          backgroundColor: iconBgMap[accent] || iconBgMap.default,
          color: iconColorMap[accent] || iconColorMap.default,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {icon}
        </div>
      </div>
      <div>
        <span style={{ fontSize: 24, fontWeight: 700, color: valueColorMap[accent] || valueColorMap.default, letterSpacing: '-0.03em', lineHeight: 1 }}>
          {value}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2" style={{ paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }} className="truncate">{sub}</span>
        {actionLabel && onAction && (
          <button
            onClick={onAction}
            style={{ fontSize: 11, fontWeight: 600, color: 'var(--error)', flexShrink: 0 }}
            className="hover:underline"
          >
            {actionLabel}
          </button>
        )}
      </div>
    </div>
  )
}

function FilterChip({ active, onClick, label }) {
  return (
    <button
      onClick={onClick}
      className={`h-8 px-3 rounded-md text-[11px] font-medium border transition-colors ${
        active
          ? 'bg-surface-3 text-on-surface border-border-strong'
          : 'bg-surface-2 border-border-subtle text-outline hover:text-on-surface hover:border-border-strong hover:bg-surface-3'
      }`}
    >
      {label}
    </button>
  )
}

function PipelineStep({ num, label, sub, tech, state }) {
  const isDone = state === 'done'
  const isActive = state === 'active'
  const isPending = state === 'pending'
  return (
    <div
      className={`flex flex-col gap-1 p-3.5 rounded-lg border text-left ${
        isDone
          ? 'bg-surface-2 border-status-success/30'
          : isActive
          ? 'bg-surface-2 border-primary/50 ring-1 ring-primary/20'
          : 'bg-surface-base border-dashed border-border-subtle opacity-70'
      }`}
    >
      {/* Step num + state icon */}
      <div className="flex items-center justify-between mb-0.5">
        <span className={`text-[10px] font-mono font-semibold uppercase ${
          isActive ? 'text-primary' : 'text-outline'
        }`}>
          {num}. {sub}
        </span>
        {isDone && <Check size={12} className="text-status-success shrink-0" />}
        {isActive && <RefreshCw size={12} className="text-primary animate-spin shrink-0" style={{ animationDuration: '2s' }} />}
        {isPending && <Clock size={12} className="text-outline shrink-0" />}
      </div>
      {/* Bold label */}
      <p className={`text-xs font-semibold leading-snug ${
        isDone ? 'text-on-surface' : isActive ? 'text-primary' : 'text-on-surface-variant'
      }`}>
        {label}
      </p>
      {/* Tech sub-description */}
      {tech && (
        <p className={`text-[10px] font-mono leading-tight mt-0.5 ${
          isActive ? 'text-primary' : 'text-outline'
        }`}>
          {tech}
        </p>
      )}
    </div>
  )
}
