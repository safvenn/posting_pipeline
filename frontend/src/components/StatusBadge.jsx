import React from 'react'
import LiveStopwatch from './LiveStopwatch'
import { getJobTiming } from '../utils/timeFormat'

const STATUS_CONFIG = {
  queued:    { label: 'Queued',    dot: '○' },
  cleaning:  { label: 'Cleaning',  dot: '◌' },
  cleaned:   { label: 'Cleaned',   dot: '●' },
  scheduled: { label: 'Scheduled', dot: '◉' },
  uploaded:  { label: 'Uploaded',  dot: '▲' },
  commented: { label: 'Commented', dot: '✓' },
  failed:    { label: 'Failed',    dot: '✕' },
}

function StatusBadgeComponent({ status, post, showTiming = false }) {
  const cfg = STATUS_CONFIG[status] || { label: status, dot: '?' }
  const isCleaning = status === 'cleaning'
  const timing = (post && showTiming && !isCleaning) ? getJobTiming(post) : null

  return (
    <span
      className={`badge badge-${status}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: isCleaning && showTiming ? '3px 8px 3px 6px' : undefined,
      }}
    >
      <span className={isCleaning ? 'spinner' : ''} style={{ fontSize: 10 }}>
        {isCleaning ? '⚡' : cfg.dot}
      </span>
      <span>{cfg.label}</span>

      {isCleaning && showTiming && (
        <LiveStopwatch
          startTime={post?.updated_at || post?.created_at}
          variant="pill"
        />
      )}

      {timing?.isCompleted && timing.durationStr && (
        <span style={{
          fontFamily: 'monospace',
          fontSize: 10,
          background: 'rgba(34, 197, 94, 0.15)',
          padding: '1px 5px',
          borderRadius: 4,
          color: '#86efac',
          marginLeft: 2,
        }}>
          {timing.durationStr}
        </span>
      )}
    </span>
  )
}

export const StatusBadge = React.memo(StatusBadgeComponent)
export default StatusBadge
