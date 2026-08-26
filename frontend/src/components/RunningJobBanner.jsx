import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight, Tv2, Sparkles, Layers } from 'lucide-react'
import LiveStopwatch from './LiveStopwatch'
import { parseUTCDate } from '../utils/timeFormat'

export default function RunningJobBanner({ runningPost, queuedCount = 0 }) {
  const navigate = useNavigate()
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  if (!runningPost || runningPost.status !== 'cleaning') return null

  const channelName = runningPost.channel_display_name || runningPost.channel?.replace(/_/g, ' ')
  const parsedStart = parseUTCDate(runningPost.updated_at || runningPost.created_at)
  const startMs = parsedStart ? parsedStart.getTime() : now
  const elapsedSec = Math.max(0, Math.floor((now - startMs) / 1000))
  const benchmarkSec = 390
  const totalEstSec = Math.max(benchmarkSec, elapsedSec + 30)
  const remainingSec = Math.max(5, totalEstSec - elapsedSec)
  const progressPct = Math.min(96, Math.max(4, Math.round((elapsedSec / totalEstSec) * 100)))

  return (
    <div
      onClick={() => navigate(`/post/${runningPost.id}`)}
      style={{
        backgroundColor: 'var(--bg-card)',
        border: '1px solid var(--border-medium)',
        borderRadius: 12,
        padding: '18px 22px',
        marginBottom: 24,
        cursor: 'pointer',
        position: 'relative',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-md)',
        transition: 'border-color var(--transition-fast), box-shadow var(--transition-fast)',
      }}
      className="card-hover"
    >
      {/* Top Accent Progress Indicator */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          height: 3,
          width: `${progressPct}%`,
          backgroundColor: 'var(--accent-primary)',
          transition: 'width 1s ease',
        }}
      />

      {/* Header Row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            backgroundColor: 'var(--accent-subtle)',
            border: '1px solid var(--accent-border)',
            padding: '3px 10px',
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 700,
            color: '#C4B5FD',
            letterSpacing: '0.04em',
            textTransform: 'uppercase',
          }}>
            <span style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              backgroundColor: 'var(--accent-primary)',
              boxShadow: '0 0 8px var(--accent-primary)',
              display: 'inline-block',
              animation: 'live-dot-ping 1.5s infinite',
            }} />
            Active Watermark Cleaner
          </span>

          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
            padding: '3px 10px',
            borderRadius: 6,
            fontSize: 11.5,
            fontWeight: 600,
            color: 'var(--text-secondary)'
          }}>
            <Tv2 size={12} color="var(--accent-primary)" />
            {channelName}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--accent-primary)', fontSize: 12, fontWeight: 600 }}>
          <span>Inspect Job</span>
          <ChevronRight size={14} />
        </div>
      </div>

      {/* Title & Post ID */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 16 }}>
        <span className="mono" style={{ color: 'var(--accent-primary)', fontSize: 13, fontWeight: 700 }}>
          #{runningPost.id}
        </span>
        <span style={{ color: 'var(--text-primary)', fontSize: 14.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '85%' }}>
          {runningPost.enriched_title || runningPost.title}
        </span>
      </div>

      {/* Stopwatch & Timers */}
      <div style={{ marginBottom: 14 }}>
        <LiveStopwatch
          startTime={runningPost.updated_at || runningPost.created_at}
          variant="hero"
        />
      </div>

      {/* Progress Bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{
          flex: 1,
          backgroundColor: 'var(--bg-subtle)',
          height: 6,
          borderRadius: 999,
          overflow: 'hidden',
          border: '1px solid var(--border-subtle)',
        }}>
          <div
            className="shimmer-bar"
            style={{
              height: '100%',
              width: `${progressPct}%`,
              backgroundColor: 'var(--accent-primary)',
              borderRadius: 999,
              transition: 'width 1s ease',
            }}
          />
        </div>
        <span
          className="tabular-nums mono"
          style={{
            fontSize: 11.5,
            fontWeight: 700,
            color: 'var(--text-secondary)',
            minWidth: 36,
            textAlign: 'right',
          }}
        >
          {progressPct}%
        </span>
      </div>

      {queuedCount > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: 'var(--accent-primary)' }}>●</span>
          <span><strong>{queuedCount}</strong> more post{queuedCount > 1 ? 's' : ''} waiting in queue</span>
        </div>
      )}
    </div>
  )
}
