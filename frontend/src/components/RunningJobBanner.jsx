import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight, Tv2, Activity } from 'lucide-react'
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
  const progressPct = Math.min(96, Math.max(4, Math.round((elapsedSec / totalEstSec) * 100)))

  return (
    <div
      onClick={() => navigate(`/post/${runningPost.id}`)}
      className="bg-surface-1 border border-primary/40 rounded-xl p-5 mb-6 relative overflow-hidden shadow-xl cursor-pointer hover:border-primary transition-all group"
    >
      {/* Top Accent Progress Indicator */}
      <div
        className="absolute top-0 left-0 h-1 bg-[#3B82F6] transition-all duration-1000 ease-out"
        style={{ width: `${progressPct}%` }}
      />

      {/* Header Row */}
      <div className="flex items-center justify-between flex-wrap gap-2.5 mb-3">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center gap-1.5 bg-[#3B82F6]/10 border border-[#3B82F6]/30 px-2.5 py-0.5 rounded-full text-mono-data-sm text-[#3B82F6] font-semibold text-xs uppercase tracking-wider">
            <span className="w-2 h-2 rounded-full bg-[#3B82F6] animate-ping" />
            Active Watermark Cleaner
          </span>

          <span className="inline-flex items-center gap-1.5 bg-surface-2 border border-border-strong px-2.5 py-0.5 rounded-lg text-mono-data-sm text-on-surface text-xs font-medium">
            <Tv2 size={12} className="text-primary" />
            {channelName}
          </span>
        </div>

        <div className="flex items-center gap-1 text-primary text-xs font-semibold group-hover:translate-x-0.5 transition-transform">
          <span>Inspect Job</span>
          <ChevronRight size={14} />
        </div>
      </div>

      {/* Title & Post ID */}
      <div className="flex items-baseline gap-2 mb-3">
        <span className="font-mono text-[#3B82F6] font-bold text-sm">
          #{runningPost.id}
        </span>
        <span className="text-on-surface font-semibold text-sm truncate max-w-[85%]">
          {runningPost.enriched_title || runningPost.title}
        </span>
      </div>

      {/* Stopwatch & Timers */}
      <div className="mb-3">
        <LiveStopwatch
          startTime={runningPost.updated_at || runningPost.created_at}
          variant="hero"
        />
      </div>

      {/* Progress Bar */}
      <div className="flex items-center gap-3">
        <div className="flex-1 bg-surface-base h-1.5 rounded-full overflow-hidden border border-border-subtle">
          <div
            className="h-full bg-[#3B82F6] rounded-full transition-all duration-1000 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <span className="font-mono text-xs font-bold text-on-surface-variant min-w-[36px] text-right">
          {progressPct}%
        </span>
      </div>

      {queuedCount > 0 && (
        <div className="text-mono-data-sm text-outline mt-2.5 flex items-center gap-1.5 text-xs">
          <Activity size={12} className="text-primary animate-pulse" />
          <span>
            <strong className="text-on-surface">{queuedCount}</strong> more post{queuedCount > 1 ? 's' : ''} waiting in transcode queue
          </span>
        </div>
      )}
    </div>
  )
}
