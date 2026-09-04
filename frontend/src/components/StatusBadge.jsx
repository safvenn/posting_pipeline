import React from 'react'
import { Check, AlertCircle, RefreshCw } from 'lucide-react'
import LiveStopwatch from './LiveStopwatch'
import { getJobTiming } from '../utils/timeFormat'

const STATUS_STYLES = {
  queued: {
    label: 'Queued',
    bg: 'bg-surface-2',
    border: 'border-border-strong',
    text: 'text-outline',
    dot: 'bg-outline',
  },
  cleaning: {
    label: 'Cleaning',
    bg: 'bg-status-info/10',
    border: 'border-status-info/30',
    text: 'text-status-info',
    dot: 'bg-status-info',
    icon: RefreshCw,
  },
  cleaned: {
    label: 'Cleaned',
    bg: 'bg-status-info/10',
    border: 'border-status-info/30',
    text: 'text-status-info',
    dot: 'bg-status-info',
  },
  scheduled: {
    label: 'Scheduled',
    bg: 'bg-status-warning/10',
    border: 'border-status-warning/30',
    text: 'text-status-warning',
    dot: 'bg-status-warning',
    pulse: true,
  },
  uploaded: {
    label: 'Scheduled',
    bg: 'bg-status-warning/10',
    border: 'border-status-warning/30',
    text: 'text-status-warning',
    dot: 'bg-status-warning',
    pulse: true,
  },
  commented: {
    label: 'Commented',
    bg: 'bg-status-success/10',
    border: 'border-status-success/30',
    text: 'text-status-success',
    dot: 'bg-status-success',
    icon: Check,
  },
  failed: {
    label: 'Failed',
    bg: 'bg-status-danger/10',
    border: 'border-status-danger/30',
    text: 'text-status-danger',
    dot: 'bg-status-danger',
    icon: AlertCircle,
  },
}

function StatusBadgeComponent({ status, post, showTiming = false }) {
  const cfg = STATUS_STYLES[status] || {
    label: status,
    bg: 'bg-surface-2',
    border: 'border-border-subtle',
    text: 'text-outline',
    dot: 'bg-outline',
  }

  const isCleaning = status === 'cleaning'
  const timing = post && showTiming && !isCleaning ? getJobTiming(post) : null

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full ${cfg.bg} border ${cfg.border} ${cfg.text} text-mono-data-sm text-[11px] font-medium transition-colors`}
    >
      {cfg.icon ? (
        <cfg.icon
          size={12}
          className={isCleaning ? 'animate-spin' : ''}
          style={isCleaning ? { animationDuration: '1.2s' } : undefined}
        />
      ) : (
        <span
          className={`w-1.5 h-1.5 rounded-full ${cfg.dot} ${cfg.pulse ? 'animate-pulse' : ''}`}
        />
      )}

      <span>{cfg.label}</span>

      {isCleaning && showTiming && (
        <LiveStopwatch
          startTime={post?.updated_at || post?.created_at}
          variant="pill"
        />
      )}

      {timing?.isCompleted && timing.durationStr && (
        <span className="text-status-success/80 font-normal ml-0.5 tabular-nums">
          {timing.durationStr}
        </span>
      )}
    </span>
  )
}

export const StatusBadge = React.memo(StatusBadgeComponent)
export default StatusBadge
