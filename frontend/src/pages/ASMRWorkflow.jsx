import React, { useState, useEffect } from 'react'
import {
  Sparkles,
  Play,
  FlaskConical,
  RefreshCw,
  Plus,
  Trash2,
  FileText,
  Layers,
  Utensils,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ExternalLink,
} from 'lucide-react'
import client from '../api/client'
import { parseUTCDate } from '../utils/timeFormat'

const statusMap = {
  pending: { label: 'Pending', bg: 'rgba(111, 120, 133, 0.15)', color: 'var(--text-secondary)' },
  selecting_food: { label: 'Selecting Food', bg: 'var(--info-subtle)', color: 'var(--info)' },
  generating_content: { label: 'Generating Content', bg: 'var(--accent-subtle)', color: 'var(--accent-primary)' },
  validating_content: { label: 'Validating Content', bg: 'var(--accent-subtle)', color: 'var(--accent-primary)' },
  generating_video: { label: 'Generating Video', bg: 'var(--accent-subtle)', color: 'var(--accent-primary)' },
  video_ready: { label: 'Video Ready', bg: 'var(--info-subtle)', color: 'var(--info)' },
  publishing: { label: 'Publishing', bg: 'var(--warning-subtle)', color: 'var(--warning)' },
  published: { label: 'Published', bg: 'var(--success-subtle)', color: 'var(--success)' },
  notified: { label: 'Notified', bg: 'var(--success-subtle)', color: '#6EE7B7' },
  failed: { label: 'Failed', bg: 'var(--error-subtle)', color: 'var(--error)' },
  retry_pending: { label: 'Retry Pending', bg: 'var(--warning-subtle)', color: 'var(--warning)' },
  dry_run_complete: { label: 'Dry Run Done', bg: 'rgba(77, 163, 255, 0.15)', color: 'var(--info)' },
}

function formatDate(d) {
  if (!d) return '—'
  const parsed = parseUTCDate(d)
  return parsed.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })
}

export default function ASMRWorkflow() {
  const [runs, setRuns] = useState([])
  const [foods, setFoods] = useState([])
  const [foodStats, setFoodStats] = useState(null)
  const [content, setContent] = useState([])
  const [loading, setLoading] = useState(false)
  const [triggerLoading, setTriggerLoading] = useState(false)
  const [newFood, setNewFood] = useState('')
  const [tab, setTab] = useState('runs')

  useEffect(() => { fetchAll() }, [])

  async function fetchAll() {
    setLoading(true)
    try {
      const [runsRes, foodsRes, statsRes, contentRes] = await Promise.all([
        client.get('/asmr/runs').catch(() => ({ data: { items: [] } })),
        client.get('/asmr/foods?limit=50').catch(() => ({ data: { items: [] } })),
        client.get('/asmr/foods/stats').catch(() => ({ data: null })),
        client.get('/asmr/content').catch(() => ({ data: { items: [] } })),
      ])
      setRuns(runsRes.data?.items || [])
      setFoods(foodsRes.data?.items || [])
      setFoodStats(statsRes.data || null)
      setContent(contentRes.data?.items || [])
    } catch (e) {
      console.error('Fetch error:', e)
    }
    setLoading(false)
  }

  async function triggerWorkflow(dryRun = false) {
    setTriggerLoading(true)
    try {
      await client.post('/asmr/run', { dry_run: dryRun })
      setTimeout(fetchAll, 1500)
    } catch (e) {
      alert('Trigger failed: ' + (e.response?.data?.detail || e.message))
    }
    setTriggerLoading(false)
  }

  async function retryRun(runId) {
    try {
      await client.post(`/asmr/runs/${runId}/retry`)
      setTimeout(fetchAll, 1500)
    } catch (e) {
      alert('Retry failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  async function addFood() {
    if (!newFood.trim()) return
    try {
      await client.post('/asmr/foods', { name: newFood.trim() })
      setNewFood('')
      fetchAll()
    } catch (e) {
      alert('Add failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  async function retireFood(id) {
    try {
      await client.delete(`/asmr/foods/${id}`)
      fetchAll()
    } catch (e) {
      alert('Retire failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  function StatusPill({ status }) {
    const s = statusMap[status] || { label: status, bg: 'var(--bg-elevated)', color: 'var(--text-secondary)' }
    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '2px 7px',
          borderRadius: 4,
          fontSize: 11,
          fontWeight: 600,
          backgroundColor: s.bg,
          color: s.color,
          border: '1px solid transparent',
        }}
      >
        {s.label}
      </span>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <Sparkles size={22} color="var(--accent-primary)" />
            ASMR Studio Workflow
          </h1>
          <div className="page-subtitle">
            Autonomous end-to-end recipe generator, SEO optimizer, video builder, and YouTube scheduler.
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={() => triggerWorkflow(true)}
            disabled={triggerLoading}
            className="btn btn-secondary btn-sm"
          >
            <FlaskConical size={13} color="var(--info)" />
            <span>Dry Run</span>
          </button>

          <button
            onClick={() => triggerWorkflow(false)}
            disabled={triggerLoading}
            className="btn btn-primary btn-sm"
          >
            {triggerLoading ? <span className="spinner" /> : <Play size={13} />}
            <span>{triggerLoading ? 'Running...' : 'Run Pipeline Now'}</span>
          </button>

          <button
            onClick={fetchAll}
            disabled={loading}
            className="btn btn-ghost btn-sm btn-icon"
          >
            <RefreshCw size={13} className={loading ? 'spinner' : ''} />
          </button>
        </div>
      </div>

      {/* Stats Summary Grid */}
      {foodStats && (
        <div className="stats-grid" style={{ marginBottom: 20 }}>
          <div className="stat-card">
            <div className="stat-icon" style={{ backgroundColor: 'rgba(124, 92, 255, 0.1)', color: 'var(--accent-primary)' }}>
              <Layers size={18} />
            </div>
            <div>
              <div className="stat-value">{foodStats.current_cycle || 1}</div>
              <div className="stat-label">Current Cycle</div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon" style={{ backgroundColor: 'rgba(77, 163, 255, 0.1)', color: 'var(--info)' }}>
              <Utensils size={18} />
            </div>
            <div>
              <div className="stat-value">{foodStats.total || 0}</div>
              <div className="stat-label">Total Recipes</div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon" style={{ backgroundColor: 'rgba(53, 208, 127, 0.1)', color: 'var(--success)' }}>
              <CheckCircle2 size={18} />
            </div>
            <div>
              <div className="stat-value">{foodStats.available || 0}</div>
              <div className="stat-label">Available</div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon" style={{ backgroundColor: 'rgba(245, 185, 66, 0.1)', color: 'var(--warning)' }}>
              <Clock size={18} />
            </div>
            <div>
              <div className="stat-value">{foodStats.used || 0}</div>
              <div className="stat-label">Used</div>
            </div>
          </div>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="tabs-nav" style={{ width: 'fit-content', marginBottom: 20 }}>
        <button
          onClick={() => setTab('runs')}
          className={`tab-item ${tab === 'runs' ? 'active' : ''}`}
        >
          Workflow Runs ({runs.length})
        </button>
        <button
          onClick={() => setTab('content')}
          className={`tab-item ${tab === 'content' ? 'active' : ''}`}
        >
          Generated Content ({content.length})
        </button>
        <button
          onClick={() => setTab('foods')}
          className={`tab-item ${tab === 'foods' ? 'active' : ''}`}
        >
          Food Repository ({foods.length})
        </button>
      </div>

      {/* Tab 1: Workflow Runs */}
      {tab === 'runs' && (
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 70 }}>Run ID</th>
                <th>Trigger</th>
                <th>Status</th>
                <th>Dry Run</th>
                <th>Started</th>
                <th>Completed</th>
                <th>Diagnostics</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="empty-state">
                      <div className="empty-state-title">No Workflow Runs Yet</div>
                      <div className="empty-state-desc">Trigger a run above to test the autonomous ASMR generator.</div>
                    </div>
                  </td>
                </tr>
              )}
              {runs.map(r => (
                <tr key={r.id}>
                  <td className="mono" style={{ color: 'var(--text-muted)', fontSize: 11.5 }}>
                    #{r.id}
                  </td>
                  <td style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
                    {r.trigger_type || 'manual'}
                  </td>
                  <td>
                    <StatusPill status={r.status} />
                  </td>
                  <td className="mono" style={{ fontSize: 11 }}>
                    {r.dry_run ? <span style={{ color: 'var(--info)' }}>✓ Yes</span> : <span style={{ color: 'var(--text-muted)' }}>No</span>}
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {formatDate(r.started_at)}
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {formatDate(r.completed_at)}
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: 'var(--error)', maxWidth: 220 }} className="truncate-text">
                    {r.error_message || '—'}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {r.status === 'failed' && (
                      <button
                        onClick={() => retryRun(r.id)}
                        className="btn btn-secondary btn-sm"
                      >
                        Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tab 2: Generated Content */}
      {tab === 'content' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {content.length === 0 && (
            <div className="card">
              <div className="empty-state">
                <div className="empty-state-title">No Generated Content</div>
                <div className="empty-state-desc">Content produced by the ASMR workflow runs will appear here.</div>
              </div>
            </div>
          )}
          {content.map(c => (
            <div key={c.id} className="card card-hover" style={{ padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>
                    {c.food_name}
                  </span>
                  <StatusPill status={c.status} />
                </div>
                <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {formatDate(c.created_at)}
                </span>
              </div>

              {c.title && (
                <div style={{ marginBottom: 8 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Title: </span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13 }}>{c.title}</span>
                </div>
              )}

              {c.description && (
                <div style={{ marginBottom: 10 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Description: </span>
                  <p style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 4, lineHeight: 1.5 }}>
                    {c.description}
                  </p>
                </div>
              )}

              {c.tags && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                  {(() => {
                    try { return JSON.parse(c.tags) } catch { return [] }
                  })().map((t, idx) => (
                    <span
                      key={idx}
                      className="mono"
                      style={{
                        backgroundColor: 'var(--bg-elevated)',
                        border: '1px solid var(--border-subtle)',
                        padding: '2px 7px',
                        borderRadius: 4,
                        fontSize: 10.5,
                        color: 'var(--text-muted)',
                      }}
                    >
                      #{t}
                    </span>
                  ))}
                </div>
              )}

              {c.video_url && (
                <div style={{ marginTop: 10 }}>
                  <a
                    href={c.video_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--accent-primary)', fontSize: 12 }}
                  >
                    <span>View Generated Video</span>
                    <ExternalLink size={11} />
                  </a>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Tab 3: Food Repository */}
      {tab === 'foods' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Add Food Input */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: 'flex', gap: 10 }}>
              <input
                value={newFood}
                onChange={e => setNewFood(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addFood()}
                placeholder="Enter recipe / food name (e.g. Masala Dosa, Butter Chicken, Jalebi)..."
                className="form-input"
              />
              <button onClick={addFood} className="btn btn-primary" style={{ flexShrink: 0 }}>
                <Plus size={14} />
                <span>Add Food</span>
              </button>
            </div>
          </div>

          {/* Foods Table */}
          <div className="data-table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Food Recipe Name</th>
                  <th>Status</th>
                  <th>Cycle #</th>
                  <th>Last Used</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {foods.map(f => (
                  <tr key={f.id}>
                    <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                      {f.name}
                    </td>
                    <td>
                      <span
                        style={{
                          display: 'inline-flex',
                          padding: '2px 6px',
                          borderRadius: 4,
                          fontSize: 10.5,
                          fontWeight: 600,
                          backgroundColor:
                            f.status === 'available' ? 'var(--success-subtle)' :
                            f.status === 'used' ? 'var(--bg-elevated)' : 'var(--error-subtle)',
                          color:
                            f.status === 'available' ? 'var(--success)' :
                            f.status === 'used' ? 'var(--text-muted)' : 'var(--error)',
                          textTransform: 'capitalize',
                        }}
                      >
                        {f.status}
                      </span>
                    </td>
                    <td className="mono" style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                      {f.cycle_number}
                    </td>
                    <td className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {formatDate(f.used_at)}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {f.status !== 'retired' && (
                        <button
                          onClick={() => retireFood(f.id)}
                          className="btn btn-danger btn-sm"
                        >
                          Retire
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
