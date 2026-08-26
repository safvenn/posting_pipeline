/**
 * Time and duration utilities for running jobs and pipeline estimation.
 */

export function parseUTCDate(isoStr) {
  if (!isoStr) return null
  if (isoStr instanceof Date) return isoStr
  let s = String(isoStr).trim()
  // If string does not end with Z or timezone offset (+XX:XX or -XX:XX), append 'Z' so JS treats as UTC
  if (!s.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(s)) {
    s += 'Z'
  }
  const parsed = new Date(s)
  return isNaN(parsed.getTime()) ? new Date() : parsed
}

export function formatDuration(seconds) {
  if (seconds == null || isNaN(seconds) || seconds < 0) return '0s'
  const s = Math.floor(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const remS = s % 60
  if (m < 60) return remS > 0 ? `${m}m ${remS}s` : `${m}m`
  const h = Math.floor(m / 60)
  const remM = m % 60
  return `${h}h ${remM}m`
}

export function formatISTTime(dateObj) {
  if (!dateObj) return ''
  const d = typeof dateObj === 'string' ? parseUTCDate(dateObj) : dateObj
  return d.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })
}

// Typical full watermark removal benchmark on remote worker (240 frames)
export const AVERAGE_CLEANING_DURATION_SEC = 390 // ~6.5 mins

export function getJobTiming(post, nowMs = Date.now()) {
  if (!post) return null

  const isCleaning = post.status === 'cleaning'
  const isQueued = post.status === 'queued'
  const isCompleted = ['cleaned', 'scheduled', 'uploaded', 'commented'].includes(post.status)
  const isFailed = post.status === 'failed'

  const startDate = parseUTCDate(post.updated_at || post.created_at)
  const createdDate = parseUTCDate(post.created_at)

  const startTime = startDate ? startDate.getTime() : nowMs
  const createdTime = createdDate ? createdDate.getTime() : nowMs

  if (isCleaning) {
    const elapsedSec = Math.max(1, Math.floor((nowMs - startTime) / 1000))
    const totalEstSec = Math.max(AVERAGE_CLEANING_DURATION_SEC, elapsedSec + 30)
    const remainingSec = Math.max(10, totalEstSec - elapsedSec)
    const progressPct = Math.min(96, Math.max(5, Math.round((elapsedSec / totalEstSec) * 100)))
    const etaDate = new Date(nowMs + remainingSec * 1000)

    return {
      status: 'cleaning',
      isRunning: true,
      elapsedSec,
      elapsedStr: formatDuration(elapsedSec),
      remainingSec,
      remainingStr: formatDuration(remainingSec),
      totalEstStr: formatDuration(totalEstSec),
      progressPct,
      etaTimeStr: formatISTTime(etaDate),
    }
  }

  if (isCompleted) {
    const updatedDate = parseUTCDate(post.updated_at)
    const updateTime = updatedDate ? updatedDate.getTime() : nowMs
    const totalDurationSec = Math.max(1, Math.floor((updateTime - createdTime) / 1000))
    return {
      status: post.status,
      isRunning: false,
      isCompleted: true,
      totalDurationSec,
      durationStr: formatDuration(totalDurationSec),
    }
  }

  return {
    status: post.status,
    isRunning: false,
    isQueued,
    isFailed,
  }
}
