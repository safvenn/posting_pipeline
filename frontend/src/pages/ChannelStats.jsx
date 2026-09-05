import React, { useState, useEffect } from 'react'
import {
  RefreshCw,
  CheckCircle,
  XCircle,
  Tv2,
  Plus,
  Trash2,
  X,
  Key,
  Settings,
  FileSpreadsheet,
  ExternalLink,
  Users,
  Film,
  AlertCircle,
  Sparkles,
  Send,
  Eye,
  EyeOff,
} from 'lucide-react'
import InstagramIcon from '../components/InstagramIcon'
import { useChannelsQuery } from '../hooks/useChannels'
import client, { formatErrorMessage } from '../api/client'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '../lib/queryClient'
import { parseUTCDate } from '../utils/timeFormat'

function fmtNumber(n) {
  if (!n) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = parseUTCDate(iso)
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })
}

function ChannelCard({ ch, onDelete, onConnect, onEdit }) {
  return (
    <div className="card" style={{ padding: 22, flex: 1, minWidth: 320, position: 'relative' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--accent-primary)',
          }}>
            <Tv2 size={20} />
          </div>
          <div>
            <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: 15, letterSpacing: '-0.01em' }}>
              {ch.display_name || ch.channel}
            </div>
            <div className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Key: {ch.channel}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            padding: '3px 8px',
            borderRadius: 6,
            fontSize: 12,
            fontWeight: 600,
            backgroundColor: ch.auth_ok ? 'var(--success-subtle)' : 'var(--error-subtle)',
            borderColor: ch.auth_ok ? 'var(--success-border)' : 'var(--error-border)',
            color: ch.auth_ok ? 'var(--success)' : 'var(--error)',
            border: '1px solid',
          }}>
            {ch.auth_ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
            <span>{ch.auth_ok ? 'YouTube OK' : 'YouTube Off'}</span>
          </span>

          <button
            onClick={() => onEdit(ch)}
            className="btn btn-ghost btn-sm btn-icon"
            title="Edit Channel Settings"
          >
            <Settings size={14} />
          </button>
          <button
            onClick={() => onDelete(ch.channel)}
            className="btn btn-danger btn-sm btn-icon"
            title="Delete Channel"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Connect Button if not auth */}
      {!ch.auth_ok && (
        <div style={{ marginBottom: 16 }}>
          <button
            onClick={() => onConnect(ch.channel)}
            className="btn btn-primary btn-sm"
            style={{ width: '100%', justifyContent: 'center' }}
          >
            <Key size={13} />
            <span>Authorize with Google OAuth</span>
          </button>
        </div>
      )}

      {/* Instagram Status Banner */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        borderRadius: 8,
        backgroundColor: ch.instagram_enabled && ch.instagram_ok ? 'rgba(225, 48, 108, 0.08)' : 'var(--bg-subtle)',
        border: `1px solid ${ch.instagram_enabled && ch.instagram_ok ? 'rgba(225, 48, 108, 0.25)' : 'var(--border-subtle)'}`,
        marginBottom: 16,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <InstagramIcon size={14} color={ch.instagram_enabled && ch.instagram_ok ? '#e1306c' : 'var(--text-muted)'} />
          <span style={{ fontSize: 12.5, fontWeight: 600, color: ch.instagram_enabled && ch.instagram_ok ? 'var(--text-primary)' : 'var(--text-muted)' }}>
            Instagram Reels:
          </span>
          <span style={{ fontSize: 12.5, color: ch.instagram_enabled && ch.instagram_ok ? '#e1306c' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {ch.instagram_enabled && ch.instagram_ok ? (ch.instagram_username ? `@${ch.instagram_username}` : 'Enabled') : 'Not Configured'}
          </span>
        </div>

        <button
          onClick={() => onEdit(ch)}
          className="btn btn-ghost btn-xs"
          style={{ fontSize: 12, color: 'var(--accent-primary)', padding: '2px 6px' }}
        >
          {ch.instagram_enabled && ch.instagram_ok ? 'Configured' : 'Setup'}
        </button>
      </div>

      {/* Stats Summary Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
        <div className="stat-card" style={{ padding: 12 }}>
          <div className="stat-icon" style={{ width: 32, height: 32, backgroundColor: 'rgba(77, 163, 255, 0.1)', color: 'var(--info)' }}>
            <Users size={15} />
          </div>
          <div>
            <div className="stat-value" style={{ fontSize: 16 }}>{fmtNumber(ch.subscriber_count)}</div>
            <div className="stat-label">Subscribers</div>
          </div>
        </div>

        <div className="stat-card" style={{ padding: 12 }}>
          <div className="stat-icon" style={{ width: 32, height: 32, backgroundColor: 'rgba(124, 92, 255, 0.1)', color: 'var(--accent-primary)' }}>
            <Film size={15} />
          </div>
          <div>
            <div className="stat-value" style={{ fontSize: 16 }}>{ch.video_count || 0}</div>
            <div className="stat-label">Total Videos</div>
          </div>
        </div>
      </div>

      {/* Connected Google Sheet Preview */}
      {ch.sheet_id && (
        <div style={{
          padding: '8px 12px',
          borderRadius: 8,
          backgroundColor: 'var(--bg-subtle)',
          border: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: 12.5,
          color: 'var(--text-secondary)',
          marginBottom: 14,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <FileSpreadsheet size={13} color="var(--success)" />
            <span style={{ fontWeight: 600 }}>Sheet:</span>
            <span className="mono truncate-text" style={{ maxWidth: 160 }}>{ch.sheet_tab || 'Default Tab'}</span>
          </div>
          <a
            href={`https://docs.google.com/spreadsheets/d/${ch.sheet_id}/edit`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-ghost btn-xs btn-icon"
            title="Open Google Sheet"
          >
            <ExternalLink size={12} />
          </a>
        </div>
      )}

      {/* Recent Uploads */}
      <div>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8 }}>
          Recent YouTube Uploads ({ch.recent_uploads?.length || 0})
        </div>
        {ch.recent_uploads && ch.recent_uploads.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {ch.recent_uploads.slice(0, 3).map(u => (
              <div
                key={u.video_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '6px 8px',
                  borderRadius: 6,
                  backgroundColor: 'var(--bg-subtle)',
                  fontSize: 12.5,
                }}
              >
                <a
                  href={`https://youtu.be/${u.video_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="truncate-text"
                  style={{ color: 'var(--text-primary)', maxWidth: 200, textDecoration: 'none' }}
                >
                  {u.title || u.video_id}
                </a>
                <span className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {fmtTime(u.published_at)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>
            No recent uploads found.
          </div>
        )}
      </div>
    </div>
  )
}

export default function ChannelStats() {
  const qc = useQueryClient()
  const {
    data: channels = [],
    isFetching: loading,
    error: channelError,
    refetch: refetchChannels,
  } = useChannelsQuery()

  const error = channelError ? formatErrorMessage(channelError) : null

  function load() { refetchChannels() }

  // Edit Modal State
  const [showEditModal, setShowEditModal] = useState(false)
  const [editChannel, setEditChannel] = useState(null)
  const [showToken, setShowToken] = useState(false)
  const [testingIg, setTestingIg] = useState(false)
  const [igTestResult, setIgTestResult] = useState(null)
  const [form, setForm] = useState({
    display_name: '',
    sheet_id: '',
    sheet_tab: '',
    seo_tags: '',
    instagram_account_id: '',
    instagram_access_token: '',
    instagram_enabled: false,
    instagram_username: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [availableSheets, setAvailableSheets] = useState([])
  const [availableTabs, setAvailableTabs] = useState([])
  const [loadingSheets, setLoadingSheets] = useState(false)
  const [loadingTabs, setLoadingTabs] = useState(false)

  async function handleConnectGlobal() {
    try {
      const res = await client.get('/channels/auth-url')
      if (res.data?.auth_url) {
        window.open(res.data.auth_url, '_blank', 'width=600,height=700')
      }
    } catch (e) {
      alert('Failed to get auth URL: ' + (e.response?.data?.detail || e.message))
    }
  }

  async function handleConnectSpecific(channelKey) {
    try {
      const res = await client.get(`/channels/${channelKey}/auth-url`)
      if (res.data?.auth_url) {
        window.open(res.data.auth_url, '_blank', 'width=600,height=700')
      }
    } catch (e) {
      alert('Failed to get auth URL: ' + (e.response?.data?.detail || e.message))
    }
  }

  function handleOpenEdit(ch) {
    setEditChannel(ch)
    setIgTestResult(null)
    setShowToken(false)
    setForm({
      display_name: ch.display_name || '',
      sheet_id: ch.sheet_id || '',
      sheet_tab: ch.sheet_tab || '',
      seo_tags: ch.seo_tags || '',
      instagram_account_id: ch.instagram_account_id || '',
      instagram_access_token: ch.instagram_access_token || '',
      instagram_enabled: ch.instagram_enabled || false,
      instagram_username: ch.instagram_username || '',
    })
    setShowEditModal(true)
    fetchSheets()
    if (ch.sheet_id) {
      fetchTabs(ch.sheet_id)
    }
  }

  function fetchSheets() {
    setLoadingSheets(true)
    client.get('/channels/google-sheets')
      .then(res => setAvailableSheets(res.data.spreadsheets || []))
      .catch(err => console.error('Failed to load sheets:', err))
      .finally(() => setLoadingSheets(false))
  }

  function fetchTabs(sheetId) {
    if (!sheetId) return
    setLoadingTabs(true)
    client.get(`/channels/google-sheets?sheet_id=${sheetId}`)
      .then(res => setAvailableTabs(res.data.tabs || []))
      .catch(err => console.error('Failed to load tabs:', err))
      .finally(() => setLoadingTabs(false))
  }

  // When sheet_id changes, fetch tabs for the new sheet
  useEffect(() => {
    if (showEditModal && form.sheet_id) {
      fetchTabs(form.sheet_id)
    } else {
      setAvailableTabs([])
    }
  }, [form.sheet_id, showEditModal])

  async function handleTestInstagram() {
    if (!form.instagram_access_token && !form.instagram_account_id) {
      setIgTestResult({ success: false, message: 'Please enter your Meta Graph Access Token (or full Graph URL).' })
      return
    }

    setTestingIg(true)
    setIgTestResult(null)
    try {
      const res = await client.post('/channels/instagram/test', {
        account_id: form.instagram_account_id || 'me',
        access_token: form.instagram_access_token,
      })
      setIgTestResult(res.data)
      if (res.data.success) {
        setForm(f => ({
          ...f,
          instagram_account_id: res.data.account_id || f.instagram_account_id,
          instagram_username: res.data.username || f.instagram_username,
          instagram_enabled: true,
        }))
      }
    } catch (e) {
      setIgTestResult({
        success: false,
        message: e.response?.data?.detail || e.message || 'Failed to connect to Instagram.',
      })
    } finally {
      setTestingIg(false)
    }
  }

  async function handleSaveEdit(e) {
    e.preventDefault()
    if (!editChannel) return
    setSubmitting(true)
    try {
      await client.put(`/channels/${editChannel.channel}`, form)
      setShowEditModal(false)
      // Invalidate shared channels cache — all pages using useChannelsQuery update
      qc.invalidateQueries({ queryKey: queryKeys.channels() })
    } catch (e) {
      alert('Error updating channel: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDeleteChannel(channelKey) {
    if (!window.confirm(`Delete channel "${channelKey}"?`)) return
    try {
      await client.delete(`/channels/${channelKey}`)
      qc.invalidateQueries({ queryKey: queryKeys.channels() })
    } catch (e) {
      alert('Error deleting channel: ' + (e.response?.data?.detail || e.message))
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <Tv2 size={22} color="var(--accent-primary)" />
            Channel &amp; Social Platform Management
          </h1>
          <div className="page-subtitle">
            Manage connected YouTube accounts, Instagram Reels credentials, Google OAuth tokens, and Google Sheet sync.
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            className="btn btn-primary"
            onClick={handleConnectGlobal}
          >
            <Key size={14} />
            <span>Connect with Google</span>
          </button>
          <button className="btn btn-secondary" onClick={load} disabled={loading} id="channels-refresh">
            <RefreshCw size={14} className={loading ? 'spinner' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="error-pill" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
            <AlertCircle size={14} /> {error}
          </div>
        </div>
      )}

      {channels.length === 0 && !loading && (
        <div className="empty-state">
          <div className="empty-state-icon">
            <Tv2 size={22} />
          </div>
          <div className="empty-state-title">No Channels Connected Yet</div>
          <div className="empty-state-desc">
            Connect your YouTube channel using Google OAuth to enable automated video uploading, metadata enrichment, and commenting.
          </div>
          <button className="btn btn-primary btn-sm" onClick={handleConnectGlobal}>
            <Key size={13} /> Connect with Google
          </button>
        </div>
      )}

      {/* Channels Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 20 }}>
        {channels.map(ch => (
          <ChannelCard
            key={ch.channel}
            ch={ch}
            onDelete={handleDeleteChannel}
            onConnect={handleConnectSpecific}
            onEdit={handleOpenEdit}
          />
        ))}
      </div>

      {/* Edit Channel Modal */}
      {showEditModal && editChannel && (
        <div className="modal-overlay" onClick={() => setShowEditModal(false)}>
          <div className="modal-card" style={{ maxWidth: 540 }} onClick={e => e.stopPropagation()}>
            <div style={{
              padding: '18px 22px',
              borderBottom: '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div>
                <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                  Configure Channel: {editChannel.display_name || editChannel.channel}
                </h2>
                <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 2 }}>
                  Set YouTube sync, Google Sheet ID, and Instagram Reels auto-posting
                </div>
              </div>
              <button
                onClick={() => setShowEditModal(false)}
                className="btn btn-ghost btn-sm btn-icon"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSaveEdit} style={{ padding: 22 }}>
              <div className="form-group">
                <label className="form-label">Display Name</label>
                <input
                  className="form-input"
                  value={form.display_name}
                  onChange={e => setForm({ ...form, display_name: e.target.value })}
                  placeholder="e.g. The Indian Kitchen"
                />
              </div>

              {/* Instagram Reels Integration Section */}
              <div style={{
                padding: 16,
                borderRadius: 10,
                backgroundColor: 'rgba(225, 48, 108, 0.04)',
                border: '1px solid rgba(225, 48, 108, 0.2)',
                marginBottom: 18,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <InstagramIcon size={18} color="#e1306c" />
                    <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-primary)' }}>
                      Instagram Reels Auto-Posting
                    </span>
                  </div>

                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
                    <input
                      type="checkbox"
                      checked={form.instagram_enabled}
                      onChange={e => setForm({ ...form, instagram_enabled: e.target.checked })}
                    />
                    <span style={{ color: form.instagram_enabled ? '#e1306c' : 'var(--text-muted)' }}>
                      {form.instagram_enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </label>
                </div>

                <div className="form-group" style={{ marginBottom: 10 }}>
                  <label className="form-label" style={{ fontSize: 12.5 }}>Instagram Account ID (Business/Creator)</label>
                  <input
                    className="form-input"
                    value={form.instagram_account_id}
                    onChange={e => setForm({ ...form, instagram_account_id: e.target.value })}
                    placeholder="e.g. 178414000000000"
                  />
                  <div className="form-hint">Found via Meta Graph API Explorer or Facebook Page Settings</div>
                </div>

                <div className="form-group" style={{ marginBottom: 10 }}>
                  <label className="form-label" style={{ fontSize: 12.5 }}>Meta Graph API Access Token (Long-Lived)</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      type={showToken ? 'text' : 'password'}
                      className="form-input"
                      value={form.instagram_access_token}
                      onChange={e => setForm({ ...form, instagram_access_token: e.target.value })}
                      placeholder="EAAG..."
                      style={{ flex: 1 }}
                    />
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setShowToken(!showToken)}
                      title="Toggle Token Visibility"
                    >
                      {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleTestInstagram}
                    disabled={testingIg || (!form.instagram_access_token && !form.instagram_account_id)}
                    style={{ fontSize: 12 }}
                  >
                    <RefreshCw size={12} className={testingIg ? 'spinner' : ''} />
                    <span>{testingIg ? 'Testing...' : 'Test Connection'}</span>
                  </button>

                  {igTestResult && (
                    <span style={{
                      fontSize: 12.5,
                      fontWeight: 600,
                      color: igTestResult.success ? 'var(--success)' : 'var(--error)',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                    }}>
                      {igTestResult.success ? <CheckCircle size={13} /> : <XCircle size={13} />}
                      <span>{igTestResult.message}</span>
                    </span>
                  )}
                </div>
              </div>

              {/* Google Sheets Sync */}
              <div className="form-group">
                <label className="form-label">Google Sheet</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <select
                    className="form-input"
                    value={form.sheet_id}
                    onChange={e => setForm({ ...form, sheet_id: e.target.value, sheet_tab: '' })}
                    disabled={loadingSheets}
                  >
                    <option value="">{loadingSheets ? 'Loading sheets...' : '-- Select a Google Sheet --'}</option>
                    {availableSheets.map(s => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                  {loadingSheets && <RefreshCw size={14} className="spinner" />}
                </div>
                {!availableSheets.length && !loadingSheets && (
                  <div className="form-hint" style={{ color: 'var(--warning)' }}>
                    No sheets found. Ensure you have shared your Google Sheet with the service account email.
                  </div>
                )}
              </div>

              <div className="form-group">
                <label className="form-label">Sheet Tab Name</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <select
                    className="form-input"
                    value={form.sheet_tab}
                    onChange={e => setForm({ ...form, sheet_tab: e.target.value })}
                    disabled={!form.sheet_id || loadingTabs}
                  >
                    <option value="">{loadingTabs ? 'Loading tabs...' : '-- Select a Tab --'}</option>
                    {availableTabs.map(t => (
                      <option key={t.id} value={t.name}>{t.name}</option>
                    ))}
                  </select>
                  {loadingTabs && <RefreshCw size={14} className="spinner" />}
                </div>
              </div>

              <div className="form-group">
                <label className="form-label">Default SEO Tags (semicolon-separated)</label>
                <textarea
                  className="form-textarea"
                  rows={2}
                  placeholder="cooking;asmr;foodie;miniature;satisfying"
                  value={form.seo_tags}
                  onChange={e => setForm({ ...form, seo_tags: e.target.value })}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20 }}>
                <button type="button" className="btn btn-ghost" onClick={() => setShowEditModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? 'Saving...' : 'Save Settings'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
