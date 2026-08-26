import React, { useState, useEffect } from 'react'
import { Timer, Clock } from 'lucide-react'
import { parseUTCDate } from '../utils/timeFormat'

const BENCHMARK_CLEANING_SEC = 390 // ~6.5 mins

function padZero(num) {
  return String(num).padStart(2, '0')
}

export function formatStopwatch(seconds) {
  if (seconds == null || isNaN(seconds) || seconds < 0) return '00:00'
  const s = Math.floor(seconds)
  const hrs = Math.floor(s / 3600)
  const mins = Math.floor((s % 3600) / 60)
  const secs = s % 60

  if (hrs > 0) {
    return `${padZero(hrs)}:${padZero(mins)}:${padZero(secs)}`
  }
  return `${padZero(mins)}:${padZero(secs)}`
}

function LiveStopwatchComponent({
  startTime,
  benchmarkSec = BENCHMARK_CLEANING_SEC,
  variant = 'compact', // 'hero' | 'compact' | 'pill'
}) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now())
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const parsedStart = parseUTCDate(startTime)
  const startMs = parsedStart ? parsedStart.getTime() : now
  const elapsedSec = Math.max(0, Math.floor((now - startMs) / 1000))
  const totalEstSec = Math.max(benchmarkSec, elapsedSec + 30)
  const remainingSec = Math.max(5, totalEstSec - elapsedSec)
  const progressPct = Math.min(96, Math.max(3, Math.round((elapsedSec / totalEstSec) * 100)))

  const etaDate = new Date(now + remainingSec * 1000)
  const etaTimeStr = etaDate.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })

  const elapsedDigital = formatStopwatch(elapsedSec)
  const remainingDigital = formatStopwatch(remainingSec)

  if (variant === 'hero') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        {/* Main Digital Stopwatch Box */}
        <div style={{
          backgroundColor: 'var(--bg-elevated)',
          border: '1px solid var(--border-medium)',
          borderRadius: 8,
          padding: '8px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <div style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            backgroundColor: 'var(--accent-primary)',
            boxShadow: '0 0 8px var(--accent-primary)',
            animation: 'live-dot-ping 1.5s infinite',
          }} />
          <div>
            <div style={{ fontSize: 9.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
              Elapsed Time
            </div>
            <div
              className="tabular-nums"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 18,
                fontWeight: 700,
                color: 'var(--text-primary)',
                letterSpacing: '0.04em',
              }}
            >
              {elapsedDigital}
            </div>
          </div>
        </div>

        {/* Est Remaining Box */}
        <div style={{
          backgroundColor: 'var(--bg-elevated)',
          border: '1px solid var(--border-medium)',
          borderRadius: 8,
          padding: '8px 14px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <Clock size={15} color="var(--warning)" />
          <div>
            <div style={{ fontSize: 9.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
              Est. Remaining
            </div>
            <div
              className="tabular-nums"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 18,
                fontWeight: 700,
                color: 'var(--warning)',
                letterSpacing: '0.04em',
              }}
            >
              ~{remainingDigital}
            </div>
          </div>
        </div>

        {/* Target ETA Info */}
        <div style={{
          backgroundColor: 'var(--bg-elevated)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 8,
          padding: '8px 14px',
        }}>
          <div style={{ fontSize: 9.5, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Target ETA</div>
          <div style={{ color: 'var(--info)', fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: 13, marginTop: 2 }}>
            {etaTimeStr}
          </div>
        </div>
      </div>
    )
  }

  if (variant === 'pill') {
    return (
      <span
        className="tabular-nums"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          backgroundColor: 'var(--accent-subtle)',
          border: '1px solid var(--accent-border)',
          padding: '1px 6px',
          borderRadius: 4,
          color: '#C4B5FD',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          fontWeight: 600,
        }}
      >
        <span>{elapsedDigital}</span>
      </span>
    )
  }

  // Default compact
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span
        className="tabular-nums"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: '#C4B5FD',
          backgroundColor: 'var(--accent-subtle)',
          border: '1px solid var(--accent-border)',
          padding: '2px 6px',
          borderRadius: 4,
          fontWeight: 600,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        <Timer size={11} color="var(--accent-primary)" />
        <span>{elapsedDigital}</span>
      </span>
      <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
        (~{remainingDigital} left)
      </span>
    </div>
  )
}

export const LiveStopwatch = React.memo(LiveStopwatchComponent)
export default LiveStopwatch
