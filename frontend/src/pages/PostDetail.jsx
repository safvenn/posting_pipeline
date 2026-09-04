import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  RotateCcw,
  Trash2,
  ExternalLink,
  Timer,
  Clock,
  Tv2,
  FileVideo,
  Layers,
  Sparkles,
  MessageSquare,
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Film,
} from 'lucide-react'
import InstagramIcon from '../components/InstagramIcon'
import StatusBadge from '../components/StatusBadge'
import LiveStopwatch from '../components/LiveStopwatch'
import { usePostQuery, useRetryPost, useDeletePost, usePublishInstagramReel } from '../hooks/usePosts'
import { getJobTiming, parseUTCDate } from '../utils/timeFormat'

function fmtTime(iso) {
  if (!iso) return '—'
  const d = parseUTCDate(iso)
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

function DetailRow({ label, value, mono = false }) {
  return (
    <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
      <td style={{
        padding: '12px 0',
        color: 'var(--text-muted)',
        fontSize: 11.5,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
        verticalAlign: 'top',
        width: 170,
      }}>
        {label}
      </td>
      <td style={{
        padding: '12px 0 12px 16px',
        color: 'var(--text-primary)',
        fontSize: 12.5,
        fontFamily: mono ? 'var(--font-mono)' : 'inherit',
        wordBreak: 'break-all',
      }}>
        {value ?? '—'}
      </td>
    </tr>
  )
}

export default function PostDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [publishingIg, setPublishingIg] = useState(false)

  // usePostQuery seeds from posts list cache — instant display when navigating from Dashboard
  // Smart polling: 10s for active statuses, 5min for terminal statuses
  const { data: post, isFetching: loading, isLoading: isInitialLoading } = usePostQuery(id)

  const retryMutation = useRetryPost()
  const deleteMutation = useDeletePost()
  const publishIgMutation = usePublishInstagramReel()

  const retrying = retryMutation.isPending
  const deleting = deleteMutation.isPending

  async function handlePublishInstagram() {
    setPublishingIg(true)
    try {
      await publishIgMutation.mutateAsync(id)
    } catch (e) {
      alert(e.response?.data?.detail || e.message || String(e))
    } finally {
      setPublishingIg(false)
    }
  }

  async function handleRetry() {
    try {
      await retryMutation.mutateAsync(id)
    } catch (e) {
      alert(e.response?.data?.detail || String(e))
    }
  }

  async function handleDelete() {
    if (!confirm('Delete this post, its files, and cancel any active processing?')) return
    try {
      await deleteMutation.mutateAsync(id)
      navigate('/')
    } catch (e) {
      alert(e.response?.data?.detail || String(e))
    }
  }

  // Show skeleton only on initial load when no cached data exists
  if (isInitialLoading && !post) {
    return (
      <div style={{ maxWidth: 840 }}>
        <div className="page-header">
          <div className="skeleton" style={{ height: 32, width: 200 }} />
        </div>
        <div className="card" style={{ padding: 24 }}>
          <div className="skeleton" style={{ height: 300, width: '100%' }} />
        </div>
      </div>
    )
  }

  if (!post) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon" style={{ color: 'var(--error)' }}>
          <AlertTriangle size={22} />
        </div>
        <div className="empty-state-title">Post Not Found</div>
        <div className="empty-state-desc">The requested post ID #{id} does not exist or was deleted.</div>
        <button className="btn btn-secondary btn-sm" onClick={() => navigate('/')}>
          <ArrowLeft size={13} /> Back to Dashboard
        </button>
      </div>
    )
  }

  const isQuota = post.error_message?.toLowerCase().includes('quota exceeded')
  const timing = getJobTiming(post)
  const channelName = post.channel_display_name || post.channel?.replace(/_/g, ' ')

  return (
    <div style={{ maxWidth: 840 }}>
      {/* Top Header */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => navigate(-1)} id="back-btn">
            <ArrowLeft size={13} />
            <span>Back</span>
          </button>
          <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 13, fontWeight: 700 }}>
            Post #{post.id}
          </span>
          <StatusBadge status={post.status} post={post} showTiming={true} />
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          {['queued', 'cleaning', 'cleaned', 'failed'].includes(post.status) && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleRetry}
              disabled={retrying}
              id="detail-retry"
            >
              {retrying ? <span className="spinner" /> : <RotateCcw size={13} />}
              <span>Retry Pipeline</span>
            </button>
          )}

          <button
            className="btn btn-danger btn-sm"
            onClick={handleDelete}
            disabled={deleting}
            id="detail-delete"
          >
            <Trash2 size={13} />
            <span>{deleting ? 'Deleting...' : 'Delete'}</span>
          </button>
        </div>
      </div>

      {/* Active Cleaning Progress Card */}
      {post.status === 'cleaning' && (
        <div
          style={{
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-medium)',
            borderRadius: 12,
            padding: 20,
            marginBottom: 20,
            boxShadow: 'var(--shadow-md)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                backgroundColor: 'var(--accent-primary)',
                boxShadow: '0 0 8px var(--accent-primary)',
                animation: 'live-dot-ping 1.5s infinite',
                display: 'inline-block',
              }} />
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                Watermark Cleaning Engine Running
              </span>
            </div>
            <span style={{ fontSize: 11.5, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Auto-refreshing live status
            </span>
          </div>

          <div style={{ marginBottom: 14 }}>
            <LiveStopwatch
              startTime={post.updated_at || post.created_at}
              variant="hero"
            />
          </div>

          <div style={{
            height: 6,
            backgroundColor: 'var(--bg-subtle)',
            borderRadius: 999,
            overflow: 'hidden',
            border: '1px solid var(--border-subtle)',
          }}>
            <div
              className="shimmer-bar"
              style={{
                height: '100%',
                width: `${timing?.progressPct || 45}%`,
                backgroundColor: 'var(--accent-primary)',
                borderRadius: 999,
                transition: 'width 1s ease',
              }}
            />
          </div>
        </div>
      )}

      {/* Error / Quota Notice */}
      {post.error_message && (
        <div className={isQuota ? 'quota-pill' : 'error-pill'} style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700, marginBottom: 4 }}>
            <AlertTriangle size={14} />
            <span>{isQuota ? 'YouTube API Daily Quota Exceeded (Resets at midnight Pacific Time)' : 'Pipeline Error'}</span>
          </div>
          <div className="mono" style={{ fontSize: 11.5, marginTop: 4 }}>
            {post.error_message}
          </div>
        </div>
      )}

      {/* Core Info Card */}
      <div className="card" style={{ padding: 22, marginBottom: 16 }}>
        <div className="section-title">
          <Layers size={16} color="var(--accent-primary)" />
          Core Metadata
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            <DetailRow
              label="Channel"
              value={
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-primary)', fontWeight: 600 }}>
                  <Tv2 size={13} color="var(--accent-primary)" />
                  {channelName}
                </span>
              }
            />
            <DetailRow
              label="Status"
              value={<StatusBadge status={post.status} post={post} showTiming={true} />}
            />
            {timing?.isCompleted && (
              <DetailRow
                label="Total Duration"
                value={
                  <span className="mono" style={{ color: 'var(--success)', fontWeight: 600 }}>
                    ⚡ {timing.durationStr}
                  </span>
                }
              />
            )}
            <DetailRow label="Original Title" value={post.title} />
            <DetailRow label="AI Enriched Title" value={post.enriched_title} />
            <DetailRow
              label="Google Sheet Row"
              value={
                post.sheet_row_id ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--info)', fontWeight: 600 }}>
                    📊 Row #{post.sheet_row_id} (Synced with Google Sheet)
                  </span>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>Auto-assigned on upload</span>
                )
              }
            />
            <DetailRow label="Scheduled Time (IST)" value={fmtTime(post.scheduled_at)} mono />
            <DetailRow label="Created At" value={fmtTime(post.created_at)} mono />
            <DetailRow label="Last Updated" value={fmtTime(post.updated_at)} mono />
            <DetailRow
              label="YouTube Video"
              value={
                post.youtube_video_id ? (
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <a
                      href={`https://www.youtube.com/watch?v=${post.youtube_video_id}`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: 'var(--accent-primary)', fontWeight: 600 }}
                    >
                      <span>Watch ({post.youtube_video_id})</span>
                      <ExternalLink size={11} />
                    </a>
                    <a
                      href={`https://studio.youtube.com/video/${post.youtube_video_id}/edit`}
                      target="_blank"
                      rel="noreferrer"
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        color: 'var(--text-secondary)',
                        fontSize: 11,
                        backgroundColor: 'var(--bg-elevated)',
                        border: '1px solid var(--border-subtle)',
                        padding: '2px 8px',
                        borderRadius: 5,
                      }}
                    >
                      <span>Open in Studio</span>
                      <ExternalLink size={10} />
                    </a>
                  </div>
                ) : null
              }
            />
            <DetailRow
              label="Instagram Reel"
              value={
                post.instagram_post_url ? (
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <a
                      href={post.instagram_post_url}
                      target="_blank"
                      rel="noreferrer"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#e1306c', fontWeight: 600 }}
                    >
                      <InstagramIcon size={13} />
                      <span>View on Instagram</span>
                      <ExternalLink size={11} />
                    </a>
                    <span style={{ fontSize: 11, color: 'var(--success)', fontWeight: 600 }}>
                      ✓ Published
                    </span>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                      {post.instagram_status === 'failed' ? (
                        <span style={{ color: 'var(--error)', fontSize: 12 }}>
                          ✗ Failed ({post.instagram_error || 'Publish error'})
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                          {post.instagram_status === 'pending' ? '⏳ Publishing...' : 'Not Published / Disabled'}
                        </span>
                      )}
                      {['scheduled', 'uploaded', 'cleaned', 'failed'].includes(post.status) && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={handlePublishInstagram}
                          disabled={publishingIg}
                          style={{
                            fontSize: 11,
                            padding: '3px 10px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            borderColor: 'rgba(225, 48, 108, 0.3)',
                            color: '#e1306c',
                          }}
                        >
                          <InstagramIcon size={12} color="#e1306c" />
                          <span>{publishingIg ? 'Publishing Reel...' : (post.instagram_status === 'failed' ? 'Retry Reel' : 'Publish Reel')}</span>
                        </button>
                      )}
                    </div>
                  </div>
                )
              }
            />
            <DetailRow
              label="Pinned Comment"
              value={post.first_comment_posted ? '✓ Posted & Active' : '✗ Not Posted'}
            />
          </tbody>
        </table>
      </div>

      {/* Content & Copywriting Card */}
      <div className="card" style={{ padding: 22, marginBottom: 16 }}>
        <div className="section-title">
          <Sparkles size={16} color="var(--accent-primary)" />
          Content &amp; Tags
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            <DetailRow label="Original Tags" value={post.tags} mono />
            <DetailRow label="AI Enriched Tags" value={post.enriched_tags} mono />
            <DetailRow
              label="Description"
              value={
                <pre style={{
                  whiteSpace: 'pre-wrap',
                  fontSize: 12,
                  color: 'var(--text-secondary)',
                  backgroundColor: 'var(--bg-subtle)',
                  padding: 12,
                  borderRadius: 8,
                  border: '1px solid var(--border-subtle)',
                  fontFamily: 'inherit',
                  margin: 0,
                }}>
                  {post.enriched_description || post.description || '—'}
                </pre>
              }
            />
            <DetailRow label="First Comment Text" value={post.first_comment_text} />
          </tbody>
        </table>
      </div>

      {/* Video Files Card */}
      <div className="card" style={{ padding: 22 }}>
        <div className="section-title">
          <Film size={16} color="var(--accent-primary)" />
          File Locations
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            <DetailRow label="Original Input" value={post.video_path} mono />
            <DetailRow label="Cleaned Video" value={post.clean_video_path} mono />
          </tbody>
        </table>
      </div>
    </div>
  )
}
