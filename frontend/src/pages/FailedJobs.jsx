import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  RefreshCw,
  RotateCcw,
  AlertTriangle,
  Tv2,
  Clock,
  Layers,
  Trash2,
  ChevronRight,
  CheckCircle2,
} from 'lucide-react'
import StatusBadge from '../components/StatusBadge'
import { usePostsQuery, useRetryPost, useClearFailedPosts } from '../hooks/usePosts'
import { parseUTCDate } from '../utils/timeFormat'

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

function isQuotaError(msg) {
  return msg && msg.toLowerCase().includes('quota exceeded')
}

export default function FailedJobs() {
  const [retrying, setRetrying] = useState({})
  const navigate = useNavigate()

  const FAILED_PARAMS = { status: 'failed' }
  const {
    data: postData,
    isFetching: loading,
    refetch,
  } = usePostsQuery(FAILED_PARAMS)

  const retryMutation = useRetryPost()
  const clearMutation = useClearFailedPosts()

  const posts = postData?.items || []

  async function handleRetry(id) {
    setRetrying(r => ({ ...r, [id]: true }))
    try {
      await retryMutation.mutateAsync(id)
    } catch (err) {
      alert(`Retry failed: ${err.response?.data?.detail || err}`)
    } finally {
      setRetrying(r => ({ ...r, [id]: false }))
    }
  }

  async function handleClearAll() {
    if (!confirm('Are you sure you want to delete all failed jobs?')) return
    try {
      await clearMutation.mutateAsync()
    } catch (err) {
      alert(`Clear failed: ${err.response?.data?.detail || err}`)
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <AlertTriangle size={22} color="var(--error)" />
            Failed Pipeline Jobs
          </h1>
          <div className="page-subtitle">
            Review error diagnostics, daily quota exceedances, and retry stalled watermark or upload jobs.
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          {posts.length > 0 && (
            <button className="btn btn-danger" onClick={handleClearAll} disabled={loading} id="failed-clear-all">
              <Trash2 size={14} />
              <span>Clear All Failed</span>
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => refetch()} disabled={loading} id="failed-refresh">
            <RefreshCw size={14} className={loading ? 'spinner' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {!postData && loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="skeleton" style={{ height: 120, width: '100%' }} />
          <div className="skeleton" style={{ height: 120, width: '100%' }} />
        </div>
      )}

      {!(!postData && loading) && posts.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon" style={{ color: 'var(--success)' }}>
            <CheckCircle2 size={24} />
          </div>
          <div className="empty-state-title">All Pipelines Healthy</div>
          <div className="empty-state-desc">
            No failed jobs found. All video processing, watermark cleaning, and uploads are running smoothly.
          </div>
          <button className="btn btn-secondary btn-sm" onClick={() => navigate('/')}>
            Back to Dashboard
          </button>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {posts.map(p => {
          const quota = isQuotaError(p.error_message)
          const channelName = p.channel_display_name || p.channel?.replace(/_/g, ' ')

          return (
            <div
              key={p.id}
              className="card card-hover"
              style={{ padding: 20 }}
              id={`failed-post-${p.id}`}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                    <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 700 }}>
                      #{p.id}
                    </span>
                    <StatusBadge status={p.status} />
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 5,
                      backgroundColor: 'var(--bg-elevated)',
                      border: '1px solid var(--border-subtle)',
                      padding: '2px 8px',
                      borderRadius: 6,
                      fontSize: 11,
                      color: 'var(--text-secondary)',
                      fontWeight: 500,
                    }}>
                      <Tv2 size={11} color="var(--accent-primary)" />
                      {channelName}
                    </span>
                  </div>

                  <div
                    onClick={() => navigate(`/post/${p.id}`)}
                    style={{
                      color: 'var(--text-primary)',
                      fontSize: 14.5,
                      fontWeight: 600,
                      marginBottom: 6,
                      cursor: 'pointer',
                    }}
                    className="truncate-text"
                  >
                    {p.enriched_title || p.title}
                  </div>

                  <div style={{ fontSize: 11.5, color: 'var(--text-muted)', marginBottom: 12, display: 'flex', gap: 12 }}>
                    <span>Created: {fmtTime(p.created_at)}</span>
                    <span>•</span>
                    <span>Updated: {fmtTime(p.updated_at)}</span>
                  </div>

                  {p.error_message && (
                    <div className={quota ? 'quota-pill' : 'error-pill'}>
                      <div style={{ fontWeight: 700, marginBottom: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <AlertTriangle size={13} />
                        <span>{quota ? 'Daily YouTube API Quota Limit' : 'Worker / Pipeline Failure'}</span>
                      </div>
                      <div className="mono" style={{ fontSize: 11.5 }}>
                        {p.error_message}
                      </div>
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => handleRetry(p.id)}
                    disabled={retrying[p.id]}
                    id={`retry-btn-${p.id}`}
                  >
                    {retrying[p.id] ? <span className="spinner" /> : <RotateCcw size={13} />}
                    <span>{retrying[p.id] ? 'Retrying...' : 'Retry Job'}</span>
                  </button>

                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => navigate(`/post/${p.id}`)}
                  >
                    <span>View Details</span>
                    <ChevronRight size={13} />
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
