import React, { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  RefreshCw,
  Tv2,
  Clock,
  Layers,
  Upload,
  CheckCircle2,
  AlertTriangle,
  PlayCircle,
  ExternalLink,
  RotateCcw,
} from 'lucide-react'
import StatusBadge from '../components/StatusBadge'
import RunningJobBanner from '../components/RunningJobBanner'
import LiveStopwatch from '../components/LiveStopwatch'
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

const StatOverview = React.memo(function StatOverview({ posts }) {
  const total = posts.length
  const inPipeline = posts.filter(p => ['queued', 'cleaning', 'cleaned'].includes(p.status)).length
  const scheduled = posts.filter(p => ['scheduled', 'uploaded'].includes(p.status)).length
  const completed = posts.filter(p => p.status === 'commented').length
  const failed = posts.filter(p => p.status === 'failed').length

  return (
    <div className="stats-grid">
      <div className="stat-card">
        <div className="stat-icon" style={{ backgroundColor: 'rgba(124, 92, 255, 0.12)', color: 'var(--accent-primary)' }}>
          <Layers size={18} />
        </div>
        <div>
          <div className="stat-value">{total}</div>
          <div className="stat-label">Total Posts</div>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-icon" style={{ backgroundColor: 'rgba(77, 163, 255, 0.12)', color: 'var(--info)' }}>
          <Clock size={18} />
        </div>
        <div>
          <div className="stat-value">{inPipeline}</div>
          <div className="stat-label">In Pipeline</div>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-icon" style={{ backgroundColor: 'rgba(245, 185, 66, 0.12)', color: 'var(--warning)' }}>
          <PlayCircle size={18} />
        </div>
        <div>
          <div className="stat-value">{scheduled}</div>
          <div className="stat-label">Scheduled</div>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-icon" style={{ backgroundColor: 'rgba(53, 208, 127, 0.12)', color: 'var(--success)' }}>
          <CheckCircle2 size={18} />
        </div>
        <div>
          <div className="stat-value">{completed}</div>
          <div className="stat-label" title="Posts that have completed the full pipeline: cleaned → uploaded → commented">Done (Commented)</div>
        </div>
      </div>

      {failed > 0 && (
        <div className="stat-card" style={{ borderColor: 'var(--error-border)' }}>
          <div className="stat-icon" style={{ backgroundColor: 'var(--error-subtle)', color: 'var(--error)' }}>
            <AlertTriangle size={18} />
          </div>
          <div>
            <div className="stat-value" style={{ color: 'var(--error)' }}>{failed}</div>
            <div className="stat-label" style={{ color: 'var(--error)' }}>Failed</div>
          </div>
        </div>
      )}
    </div>
  )
})

export default function Dashboard() {
  const [channel, setChannel] = useState('all')
  const [status, setStatus] = useState('all')
  const [resetMsg, setResetMsg] = useState('')
  const navigate = useNavigate()

  // Memoized params — stable object reference prevents extra query key changes
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

  // Channels shared from cache — Dashboard and ScheduleCalendar share one request
  const { data: channels = [] } = useChannelsQuery()

  // Dedicated 4s-poll for running job — does NOT re-render the whole dashboard
  const { data: runningJobData } = useRunningJobQuery()

  const resetStuck = useResetStuck()

  const posts = postData?.items || []
  const total = postData?.total || 0

  const queuedCount = useMemo(() => posts.filter(p => p.status === 'queued').length, [posts])
  const stuckCount = useMemo(() => posts.filter(p => ['cleaning', 'cleaned'].includes(p.status)).length, [posts])

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

  // Only show skeleton on very first load when no cache exists
  const isInitialLoad = !postData && postsFetching

  return (
    <div>
      {/* Top Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <Layers size={22} color="var(--accent-primary)" />
            Pipeline Dashboard
          </h1>
          <div className="page-subtitle">
            Monitor real-time video processing, watermark cleaning, and automated publishing.
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {stuckCount > 0 && (
            <button
              className="btn btn-secondary"
              onClick={handleResetStuck}
              title={`${stuckCount} job(s) stuck in cleaned/cleaning — click to re-queue`}
              style={{ color: 'var(--warning, #f59e0b)', borderColor: 'var(--warning, #f59e0b)' }}
            >
              <RotateCcw size={14} />
              <span>Reset Stuck ({stuckCount})</span>
            </button>
          )}

          <button
            className="btn btn-secondary"
            onClick={() => refetchPosts()}
            disabled={postsFetching}
            aria-label="Refresh posts"
          >
            <RefreshCw size={14} className={postsFetching ? 'spinner' : ''} />
            <span>Refresh</span>
          </button>

          <button
            className="btn btn-primary"
            onClick={() => navigate('/upload')}
          >
            <Upload size={14} />
            <span>Upload Video</span>
          </button>
        </div>
      </div>

      {resetMsg && (
        <div style={{ margin: '0 0 12px', padding: '10px 16px', backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)', borderRadius: 8, fontSize: 13, color: 'var(--accent-primary)' }}>
          ✓ {resetMsg}
        </div>
      )}

      {/* Active Running Job Banner — dedicated 4s-poll endpoint */}
      <RunningJobBanner runningPost={runningJobData} queuedCount={queuedCount} />

      {/* Stats Summary Grid */}
      <StatOverview posts={posts} />

      {/* Filter Navigation Bar */}
      <div className="card" style={{ padding: '12px 16px', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          {/* Channel Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: 4 }}>
              Channel:
            </span>
            <div className="tabs-nav">
              <button
                className={`tab-item ${channel === 'all' ? 'active' : ''}`}
                onClick={() => setChannel('all')}
              >
                All
              </button>
              {channels.map(c => (
                <button
                  key={c.channel}
                  className={`tab-item ${channel === c.channel ? 'active' : ''}`}
                  onClick={() => setChannel(c.channel)}
                >
                  {c.display_name || c.channel}
                </button>
              ))}
            </div>
          </div>

          {/* Status Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: 4 }}>
              Status:
            </span>
            <div className="tabs-nav">
              {STATUSES.map(s => (
                <button
                  key={s.id}
                  className={`tab-item ${status === s.id ? 'active' : ''}`}
                  onClick={() => setStatus(s.id)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Posts Table */}
      <div className="data-table-container" style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch', width: '100%' }}>
        <table className="data-table" style={{ minWidth: 680 }}>
          <thead>
            <tr>
              <th style={{ width: 70 }}>ID</th>
              <th>Post Title</th>
              <th>Channel</th>
              <th>Status &amp; Timing</th>
              <th>Scheduled Time</th>
              <th>YouTube Link</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {isInitialLoad && (
              <tr>
                <td colSpan={7} style={{ padding: '32px 16px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    <div className="skeleton" style={{ height: 24, width: '100%' }} />
                    <div className="skeleton" style={{ height: 24, width: '90%' }} />
                    <div className="skeleton" style={{ height: 24, width: '95%' }} />
                  </div>
                </td>
              </tr>
            )}

            {!isInitialLoad && posts.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="empty-state">
                    <div className="empty-state-icon">
                      <Layers size={22} />
                    </div>
                    <div className="empty-state-title">No posts found</div>
                    <div className="empty-state-desc">
                      {status !== 'all' || channel !== 'all'
                        ? 'Try changing the filters above to view other posts.'
                        : 'Upload a video to start the automated watermark removal and publishing pipeline.'}
                    </div>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => navigate('/upload')}
                    >
                      <Upload size={13} />
                      Upload New Video
                    </button>
                  </div>
                </td>
              </tr>
            )}

            {posts.map(p => {
              const channelLabel = p.channel_display_name || p.channel?.replace(/_/g, ' ')

              return (
                <tr
                  key={p.id}
                  onClick={() => navigate(`/post/${p.id}`)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      navigate(`/post/${p.id}`)
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  className="table-row-interactive"
                  id={`post-row-${p.id}`}
                  style={{ cursor: 'pointer' }}
                >
                  <td className="mono" style={{ color: 'var(--text-muted)', fontSize: 11.5, fontWeight: 600 }}>
                    #{p.id}
                  </td>
                  <td>
                    <div className="truncate-text" style={{ color: 'var(--text-primary)', maxWidth: 280, fontWeight: 600 }}>
                      {p.enriched_title || p.title}
                    </div>
                    {p.enriched_title && p.enriched_title !== p.title && (
                      <div className="truncate-text" style={{ color: 'var(--text-muted)', fontSize: 11, maxWidth: 280, marginTop: 2 }}>
                        orig: {p.title}
                      </div>
                    )}
                  </td>
                  <td>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                      backgroundColor: 'var(--bg-elevated)',
                      border: '1px solid var(--border-subtle)',
                      padding: '3px 8px',
                      borderRadius: 6,
                      fontSize: 11,
                      color: 'var(--text-secondary)',
                      fontWeight: 500,
                    }}>
                      <Tv2 size={11} color="var(--accent-primary)" />
                      {channelLabel}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5, alignItems: 'flex-start' }}>
                      <StatusBadge status={p.status} post={p} showTiming={true} />
                      {p.status === 'cleaning' && (
                        <LiveStopwatch
                          startTime={p.updated_at || p.created_at}
                          variant="compact"
                        />
                      )}
                    </div>
                  </td>
                  <td className="mono" style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                    {fmtTime(p.scheduled_at)}
                  </td>
                  <td className="mono" style={{ fontSize: 11.5 }}>
                    {p.youtube_video_id ? (
                      <a
                        href={`https://www.youtube.com/watch?v=${p.youtube_video_id}`}
                        target="_blank"
                        rel="noreferrer"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--accent-primary)' }}
                        onClick={e => e.stopPropagation()}
                      >
                        <span>{p.youtube_video_id}</span>
                        <ExternalLink size={10} />
                      </a>
                    ) : (
                      <span style={{ color: 'var(--text-subtle)' }}>—</span>
                    )}
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {fmtTime(p.created_at)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {/* Footer Summary */}
        <div style={{
          padding: '10px 16px',
          backgroundColor: 'var(--bg-subtle)',
          borderTop: '1px solid var(--border-subtle)',
          color: 'var(--text-muted)',
          fontSize: 11.5,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div>
            Showing <strong>{posts.length}</strong> of <strong>{total}</strong> posts
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>Auto-refreshing (15s)</span>
            <span style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              backgroundColor: postsFetching ? 'var(--warning)' : 'var(--success)',
            }} />
          </div>
        </div>
      </div>
    </div>
  )
}
