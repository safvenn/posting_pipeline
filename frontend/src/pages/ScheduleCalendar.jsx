import React, { useState, useEffect } from 'react'
import {
  RefreshCw,
  Calendar as CalendarIcon,
  Clock,
  Tv2,
  ExternalLink,
  GripVertical,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
  Trash2,
} from 'lucide-react'
import InstagramIcon from '../components/InstagramIcon'
import StatusBadge from '../components/StatusBadge'
import { getSchedule, rescheduleSlot, clearFailedSchedules } from '../api/schedule'
import { getChannels } from '../api/channels'
import { parseUTCDate } from '../utils/timeFormat'

function fmtDate(iso) {
  const d = parseUTCDate(iso)
  return d.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

function fmtTime(iso) {
  const d = parseUTCDate(iso)
  return d.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })
}

export default function ScheduleCalendar() {
  const [slots, setSlots] = useState([])
  const [channels, setChannels] = useState([])
  const [days, setDays] = useState(7)
  const [loading, setLoading] = useState(false)
  const [rescheduling, setRescheduling] = useState(false)
  const [draggedItem, setDraggedItem] = useState(null)
  const [dragOverKey, setDragOverKey] = useState(null)
  const [notification, setNotification] = useState(null)

  function showNotification(type, message) {
    setNotification({ type, message })
    setTimeout(() => setNotification(null), 4000)
  }

  function load() {
    setLoading(true)
    Promise.all([
      getSchedule(days),
      getChannels().catch(() => [])
    ])
      .then(([scheduleData, channelsData]) => {
        setSlots(scheduleData || [])
        if (Array.isArray(channelsData) && channelsData.length > 0) {
          setChannels(channelsData)
        } else {
          const distinct = Array.from(new Set((scheduleData || []).map(s => s.channel)))
          setChannels(distinct.map(k => ({ channel: k, display_name: k })))
        }
      })
      .catch(err => {
        console.error(err)
        showNotification('error', 'Failed to fetch schedule data.')
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [days])

  // Group slots by date -> channel -> slot_label or off_slot list
  const byDate = {}
  for (const s of slots) {
    const d = parseUTCDate(s.scheduled_at).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
    if (!byDate[d]) byDate[d] = {}
    if (!byDate[d][s.channel]) byDate[d][s.channel] = { A: null, B: null, off_slots: [] }

    if (s.slot_label === 'A') {
      byDate[d][s.channel].A = s
    } else if (s.slot_label === 'B') {
      byDate[d][s.channel].B = s
    } else {
      byDate[d][s.channel].off_slots.push(s)
    }
  }

  const dates = Object.keys(byDate).sort()
  const channelKeys = channels.length > 0 ? channels.map(c => c.channel) : Array.from(new Set(slots.map(s => s.channel)))

  // Drag & Drop Handlers
  function handleDragStart(e, item) {
    setDraggedItem(item)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('application/json', JSON.stringify({
      post_id: item.post_id,
      youtube_video_id: item.youtube_video_id,
      channel: item.channel,
      title: item.post_title,
      scheduled_at: item.scheduled_at,
    }))
  }

  function handleDragEnd() {
    setDraggedItem(null)
    setDragOverKey(null)
  }

  async function handleDrop(e, targetDateStr, targetSlotLabel, targetSlotTimeISO, channelKey) {
    e.preventDefault()
    setDragOverKey(null)

    if (!draggedItem) return
    if (!draggedItem.post_id && !draggedItem.youtube_video_id) {
      showNotification('error', 'Cannot reschedule this item (missing identifier).')
      return
    }

    setRescheduling(true)
    try {
      const res = await rescheduleSlot({
        post_id: draggedItem.post_id,
        youtube_video_id: draggedItem.youtube_video_id,
        channel: channelKey || draggedItem.channel,
        new_scheduled_at: targetSlotTimeISO,
      })

      showNotification('success', res.message || 'Video successfully rescheduled!')
      load()
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Failed to reschedule video.'
      showNotification('error', msg)
    } finally {
      setRescheduling(false)
      setDraggedItem(null)
    }
  }

  async function handleClearFailed() {
    if (!confirm('Clear schedule timestamps from any failed posts so slots become available?')) return
    try {
      const res = await clearFailedSchedules()
      showNotification('success', res.message || 'Cleared failed schedules')
      load()
    } catch (err) {
      showNotification('error', 'Failed to clear failed schedules')
    }
  }

  return (
    <div>
      {/* Toast Notification */}
      {notification && (
        <div
          style={{
            position: 'fixed',
            top: 24,
            right: 24,
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '12px 18px',
            borderRadius: 10,
            fontSize: 13,
            fontWeight: 500,
            backgroundColor: notification.type === 'success' ? 'var(--bg-elevated, #18181b)' : 'var(--error-subtle, #450a0a)',
            color: notification.type === 'success' ? '#22c55e' : '#ef4444',
            border: `1px solid ${notification.type === 'success' ? '#22c55e44' : '#ef444466'}`,
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            animation: 'fadeIn 0.2s ease-in-out',
          }}
        >
          {notification.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          <span>{notification.message}</span>
        </div>
      )}

      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <CalendarIcon size={22} color="var(--accent-primary)" />
            Schedule Matrix &amp; Timetable
          </h1>
          <div className="page-subtitle">
            The 2 daily viral peak publishing slots (12:30 PM &amp; 6:30 PM IST) with live YouTube syncing &amp; drag-and-drop rescheduling.
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="form-select"
            style={{ width: 130 }}
            id="schedule-days-select"
          >
            <option value={7}>Next 7 Days</option>
            <option value={14}>Next 14 Days</option>
            <option value={30}>Next 30 Days</option>
          </select>

          <button
            className="btn btn-secondary btn-sm"
            onClick={handleClearFailed}
            title="Clear and reset schedule timestamps from failed posts"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
          >
            <Trash2 size={13} />
            <span>Clear Failed</span>
          </button>

          <button className="btn btn-secondary" onClick={load} disabled={loading || rescheduling}>
            <RefreshCw size={14} className={loading || rescheduling ? 'spinner' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Legend & Viral Timing Info Card */}
      <div className="card" style={{ padding: '14px 20px', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 14 }}>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center', fontSize: 12, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 7, alignItems: 'center' }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, backgroundColor: 'var(--bg-subtle)', border: '1px dashed var(--accent-primary)', display: 'inline-block' }} />
              <span style={{ color: 'var(--text-muted)' }}>Available Viral Slot (Drop here)</span>
            </div>
            <div style={{ display: 'flex', gap: 7, alignItems: 'center' }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--accent-border)', display: 'inline-block' }} />
              <span style={{ color: 'var(--text-secondary)' }}>Scheduled Post (Draggable)</span>
            </div>
            <div style={{ display: 'flex', gap: 7, alignItems: 'center' }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, backgroundColor: 'rgba(34, 197, 94, 0.2)', border: '1px solid rgba(34, 197, 94, 0.4)', display: 'inline-block' }} />
              <span style={{ color: 'var(--success)' }}>✓ Posted (Fixed)</span>
            </div>
            <div style={{ display: 'flex', gap: 7, alignItems: 'center' }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, backgroundColor: '#78350f22', border: '1px solid #f59e0b', display: 'inline-block' }} />
              <span style={{ color: '#f59e0b' }}>Off-Schedule Time</span>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 10px',
              borderRadius: 6,
              backgroundColor: 'rgba(225, 48, 108, 0.08)',
              border: '1px solid rgba(225, 48, 108, 0.25)',
              color: '#e1306c',
              fontSize: 11.5,
              fontWeight: 600,
            }}>
              <InstagramIcon size={13} color="#e1306c" />
              <span>Instagram Reels Auto-Posting Active</span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--accent-primary)', fontSize: 12, fontWeight: 500 }}>
              <Sparkles size={14} />
              <span>Viral Peaks: Slot A (12:30 PM) &amp; Slot B (6:30 PM IST)</span>
            </div>
          </div>
        </div>
      </div>

      {/* Calendar Matrix Grid */}
      <div className="data-table-container">
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 780 }}>
            <thead>
              <tr>
                <th style={{ width: 130 }}>Date</th>
                {channels.map(c => (
                  <th
                    key={`${c.channel}-slots`}
                    colSpan={2}
                    style={{
                      textAlign: 'center',
                      color: 'var(--text-primary)',
                      borderLeft: '1px solid var(--border-subtle)',
                    }}
                  >
                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <Tv2 size={13} color="var(--accent-primary)" />
                      <span>{c.display_name || c.channel}</span>
                    </div>
                  </th>
                ))}
              </tr>
              <tr>
                <th style={{ borderBottom: '1px solid var(--border-subtle)' }} />
                {channels.map(c => (
                  ['Slot A (12:30 PM IST - Lunch Peak)', 'Slot B (06:30 PM IST - Prime Peak)'].map((slotName, i) => (
                    <th
                      key={`${c.channel}-${i}`}
                      style={{
                        textAlign: 'center',
                        fontSize: 10.5,
                        fontWeight: 600,
                        color: 'var(--text-muted)',
                        padding: '8px 10px',
                        borderLeft: i === 0 ? '1px solid var(--border-subtle)' : 'none',
                      }}
                    >
                      {slotName}
                    </th>
                  ))
                ))}
              </tr>
            </thead>
            <tbody>
              {dates.map(d => {
                const row = byDate[d]
                // Check if any channel has off-slot videos on this day
                const hasOffSlots = channelKeys.some(ch => row?.[ch]?.off_slots && row[ch].off_slots.length > 0)

                return (
                  <React.Fragment key={d}>
                    <tr>
                      <td style={{ padding: '12px 16px', verticalAlign: 'middle' }}>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>
                          {fmtDate(d + 'T00:00:00')}
                        </div>
                        <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                          {d}
                        </div>
                      </td>
                      {channelKeys.flatMap(ch => ['A', 'B'].map((label, idx) => {
                        const s = row?.[ch]?.[label]
                        const defaultTimeLabel = label === 'A' ? '12:30 PM IST' : '06:30 PM IST'
                        const slotKey = `${d}-${ch}-${label}`
                        const isDragTarget = dragOverKey === slotKey

                        if (!s) {
                          return (
                            <td
                              key={slotKey}
                              style={{
                                padding: '10px 12px',
                                borderLeft: idx === 0 ? '1px solid var(--border-subtle)' : 'none',
                              }}
                            >
                              <div style={{
                                backgroundColor: 'var(--bg-subtle)',
                                border: '1px dashed var(--border-subtle)',
                                borderRadius: 8,
                                padding: '12px 10px',
                                textAlign: 'center',
                                fontSize: 11,
                                color: 'var(--text-muted)',
                              }}>
                                <span>{defaultTimeLabel}</span>
                                <div style={{ fontSize: 10, color: 'var(--text-subtle)', marginTop: 2 }}>Available Slot</div>
                              </div>
                            </td>
                          )
                        }

                        const isFailed = s.status === 'failed'
                        const isAvail = s.is_available
                        const isOccupied = !isAvail && s.post_title
                        const isPosted = ['uploaded', 'commented'].includes(s.status) || (new Date(s.scheduled_at) < new Date() && Boolean(s.youtube_video_id))

                        return (
                          <td
                            key={slotKey}
                            onDragOver={e => {
                              if (isAvail && draggedItem && !isPosted) {
                                e.preventDefault()
                                setDragOverKey(slotKey)
                              }
                            }}
                            onDragLeave={() => {
                              if (dragOverKey === slotKey) setDragOverKey(null)
                            }}
                            onDrop={e => {
                              if (isAvail && !isPosted) {
                                handleDrop(e, d, label, s.scheduled_at, ch)
                              }
                            }}
                            style={{
                              padding: '10px 12px',
                              borderLeft: idx === 0 ? '1px solid var(--border-subtle)' : 'none',
                              backgroundColor: isDragTarget ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
                              transition: 'background-color 0.2s',
                            }}
                          >
                            {isOccupied ? (
                              <div
                                draggable={!isPosted}
                                onDragStart={e => !isPosted && handleDragStart(e, s)}
                                onDragEnd={handleDragEnd}
                                style={{
                                  backgroundColor: isFailed ? 'var(--error-subtle)' : isPosted ? 'rgba(34, 197, 94, 0.06)' : 'var(--bg-elevated)',
                                  border: `1px solid ${isFailed ? 'var(--error-border)' : isPosted ? 'rgba(34, 197, 94, 0.35)' : 'var(--accent-border, #6366f144)'}`,
                                  borderRadius: 8,
                                  padding: '10px 12px',
                                  cursor: isPosted ? 'default' : 'grab',
                                  position: 'relative',
                                  boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                                  transition: 'transform 0.15s, box-shadow 0.15s',
                                }}
                                className={isPosted ? '' : 'scheduled-card-hover'}
                              >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10.5, color: isPosted ? 'var(--success, #22c55e)' : 'var(--accent-primary)', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                                    <Clock size={11} />
                                    <span>{fmtTime(s.scheduled_at)}</span>
                                  </div>

                                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                    {isPosted ? (
                                      <span
                                        style={{
                                          fontSize: 10,
                                          fontWeight: 700,
                                          color: 'var(--success, #22c55e)',
                                          display: 'inline-flex',
                                          alignItems: 'center',
                                          gap: 3,
                                          backgroundColor: 'rgba(34, 197, 94, 0.12)',
                                          padding: '2px 6px',
                                          borderRadius: 4,
                                          border: '1px solid rgba(34, 197, 94, 0.3)',
                                        }}
                                        title="Video is published and fixed in place"
                                      >
                                        <CheckCircle2 size={11} /> Posted
                                      </span>
                                    ) : (
                                      <GripVertical size={13} color="var(--text-muted)" style={{ cursor: 'grab' }} />
                                    )}

                                    {s.youtube_video_id && (
                                      <a
                                        href={`https://studio.youtube.com/video/${s.youtube_video_id}/edit`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="btn btn-ghost btn-xs btn-icon"
                                        title="Open YouTube Studio Video Editor"
                                        style={{ height: 20, width: 20, padding: 0 }}
                                        onClick={e => e.stopPropagation()}
                                      >
                                        <ExternalLink size={12} color={isPosted ? 'var(--success, #22c55e)' : 'var(--accent-primary)'} />
                                      </a>
                                    )}
                                  </div>
                                </div>

                                <div
                                  className="truncate-text"
                                  style={{
                                    fontSize: 12,
                                    fontWeight: 600,
                                    color: 'var(--text-primary)',
                                    marginBottom: 6,
                                    maxWidth: 220,
                                  }}
                                  title={s.post_title}
                                >
                                  {s.post_title}
                                </div>

                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4, flexWrap: 'wrap', gap: 6 }}>
                                  {s.status && <StatusBadge status={s.status} />}
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                    {s.instagram_post_url ? (
                                      <a
                                        href={s.instagram_post_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{
                                          fontSize: 10,
                                          color: '#e1306c',
                                          display: 'inline-flex',
                                          alignItems: 'center',
                                          gap: 3,
                                          textDecoration: 'none',
                                          fontWeight: 600,
                                          backgroundColor: 'rgba(225, 48, 108, 0.08)',
                                          padding: '2px 5px',
                                          borderRadius: 4,
                                          border: '1px solid rgba(225, 48, 108, 0.2)',
                                        }}
                                        title="Open Published Instagram Reel"
                                        onClick={e => e.stopPropagation()}
                                      >
                                        <InstagramIcon size={10} color="#e1306c" />
                                        <span>Reel ✓</span>
                                      </a>
                                    ) : s.instagram_status === 'pending' ? (
                                      <span
                                        style={{
                                          fontSize: 10,
                                          color: '#e1306c',
                                          display: 'inline-flex',
                                          alignItems: 'center',
                                          gap: 3,
                                          fontWeight: 600,
                                          backgroundColor: 'rgba(225, 48, 108, 0.08)',
                                          padding: '2px 5px',
                                          borderRadius: 4,
                                        }}
                                        title="Publishing to Instagram Reels"
                                      >
                                        <InstagramIcon size={10} color="#e1306c" />
                                        <span>⏳ Posting</span>
                                      </span>
                                    ) : s.instagram_enabled ? (
                                      <span
                                        style={{
                                          fontSize: 10,
                                          color: '#e1306c',
                                          display: 'inline-flex',
                                          alignItems: 'center',
                                          gap: 3,
                                          fontWeight: 600,
                                          backgroundColor: 'rgba(225, 48, 108, 0.08)',
                                          padding: '2px 5px',
                                          borderRadius: 4,
                                          border: '1px solid rgba(225, 48, 108, 0.2)',
                                        }}
                                        title="This post will also auto-publish to Instagram Reels"
                                      >
                                        <InstagramIcon size={10} color="#e1306c" />
                                        <span>Insta Sync</span>
                                      </span>
                                    ) : null}

                                    {s.youtube_video_id && (
                                      <a
                                        href={`https://studio.youtube.com/video/${s.youtube_video_id}/edit`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{
                                          fontSize: 10,
                                          color: 'var(--accent-primary)',
                                          display: 'inline-flex',
                                          alignItems: 'center',
                                          gap: 3,
                                          textDecoration: 'none',
                                        }}
                                        onClick={e => e.stopPropagation()}
                                      >
                                        <span>Studio</span>
                                        <ExternalLink size={10} />
                                      </a>
                                    )}
                                  </div>
                                </div>
                              </div>
                            ) : isAvail ? (
                              <div
                                onDragOver={e => {
                                  if (draggedItem) {
                                    e.preventDefault()
                                    setDragOverKey(slotKey)
                                  }
                                }}
                                onDrop={e => handleDrop(e, d, label, s.scheduled_at, ch)}
                                style={{
                                  backgroundColor: isDragTarget ? 'rgba(99, 102, 241, 0.25)' : 'var(--bg-subtle)',
                                  border: `2px dashed ${isDragTarget ? 'var(--accent-primary, #6366f1)' : 'var(--border-subtle)'}`,
                                  borderRadius: 8,
                                  padding: '12px 10px',
                                  textAlign: 'center',
                                  fontSize: 11,
                                  color: isDragTarget ? 'var(--accent-primary)' : 'var(--text-muted)',
                                  transition: 'all 0.2s',
                                  cursor: draggedItem ? 'copy' : 'default',
                                }}
                              >
                                <div style={{ fontWeight: 600, fontSize: 11 }}>{defaultTimeLabel}</div>
                                <div style={{ fontSize: 10, color: isDragTarget ? 'var(--accent-primary)' : 'var(--success, #22c55e)', marginTop: 2 }}>
                                  {isDragTarget ? 'Drop here to reschedule' : '🟢 Open Slot (Drop here)'}
                                </div>
                              </div>
                            ) : (
                              <div style={{
                                backgroundColor: 'var(--bg-subtle)',
                                border: '1px solid var(--border-subtle)',
                                borderRadius: 8,
                                padding: '10px',
                                textAlign: 'center',
                                fontSize: 11,
                                color: 'var(--text-muted)',
                                opacity: 0.6,
                              }}>
                                <span>{defaultTimeLabel}</span>
                                <div style={{ fontSize: 10, color: 'var(--text-subtle)', marginTop: 2 }}>Past Slot</div>
                              </div>
                            )}
                          </td>
                        )
                      }))}
                    </tr>

                    {/* Off-Slot / Custom-Time Row if any post was scheduled outside standard slots */}
                    {hasOffSlots && (
                      <tr style={{ backgroundColor: 'rgba(245, 158, 11, 0.04)', borderBottom: '1px solid var(--border-subtle)' }}>
                        <td style={{ padding: '8px 16px', fontSize: 11, color: '#f59e0b', fontWeight: 600 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            <AlertTriangle size={13} />
                            <span>Off-Schedule</span>
                          </div>
                        </td>
                        {channelKeys.map(ch => {
                          const offList = row?.[ch]?.off_slots || []
                          return (
                            <td key={`${d}-${ch}-off`} colSpan={2} style={{ padding: '8px 12px' }}>
                              {offList.length > 0 ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                  {offList.map((item, i) => {
                                    const isItemPosted = ['uploaded', 'commented'].includes(item.status) || (new Date(item.scheduled_at) < new Date() && Boolean(item.youtube_video_id))
                                    return (
                                      <div
                                        key={i}
                                        draggable={!isItemPosted}
                                        onDragStart={e => !isItemPosted && handleDragStart(e, item)}
                                        onDragEnd={handleDragEnd}
                                        style={{
                                          display: 'flex',
                                          alignItems: 'center',
                                          justifyContent: 'space-between',
                                          padding: '6px 10px',
                                          backgroundColor: isItemPosted ? 'rgba(34, 197, 94, 0.06)' : '#78350f22',
                                          border: `1px solid ${isItemPosted ? 'rgba(34, 197, 94, 0.35)' : '#f59e0b55'}`,
                                          borderRadius: 6,
                                          fontSize: 11.5,
                                          cursor: isItemPosted ? 'default' : 'grab',
                                        }}
                                      >
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                                          {isItemPosted ? (
                                            <span style={{ fontSize: 9.5, fontWeight: 700, color: 'var(--success, #22c55e)', display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                                              <CheckCircle2 size={10} /> Posted
                                            </span>
                                          ) : (
                                            <GripVertical size={12} color="#f59e0b" />
                                          )}
                                          <span style={{ fontWeight: 600, color: isItemPosted ? 'var(--success, #22c55e)' : '#f59e0b', fontFamily: 'var(--font-mono)' }}>
                                            {fmtTime(item.scheduled_at)}
                                          </span>
                                          <span className="truncate-text" style={{ color: 'var(--text-primary)', maxWidth: 220 }}>
                                            {item.post_title}
                                          </span>
                                        </div>

                                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                          {item.instagram_post_url ? (
                                            <a
                                              href={item.instagram_post_url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              className="btn btn-ghost btn-xs btn-icon"
                                              title="Open Instagram Reel"
                                              onClick={e => e.stopPropagation()}
                                              style={{ height: 20, width: 20, padding: 0 }}
                                            >
                                              <InstagramIcon size={12} color="#e1306c" />
                                            </a>
                                          ) : item.instagram_enabled ? (
                                            <span style={{ fontSize: 9.5, color: '#e1306c', display: 'inline-flex', alignItems: 'center', gap: 2 }} title="Instagram Reels Sync Active">
                                              <InstagramIcon size={10} color="#e1306c" />
                                            </span>
                                          ) : null}

                                          {item.youtube_video_id && (
                                            <a
                                              href={`https://studio.youtube.com/video/${item.youtube_video_id}/edit`}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              className="btn btn-ghost btn-xs btn-icon"
                                              title="Open in YouTube Studio"
                                              onClick={e => e.stopPropagation()}
                                              style={{ height: 20, width: 20, padding: 0 }}
                                            >
                                              <ExternalLink size={12} color="#f59e0b" />
                                            </a>
                                          )}
                                          {!isItemPosted && (
                                            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                                              Drag to Slot A/B
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                    )
                                  })}
                                </div>
                              ) : (
                                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>—</span>
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

