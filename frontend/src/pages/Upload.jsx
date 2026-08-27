import React, { useState, useRef, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Upload as UploadIcon,
  FileVideo,
  X,
  Sparkles,
  RefreshCw,
  FileSpreadsheet,
  Tv2,
  CheckCircle2,
  AlertCircle,
  Clock,
  ArrowRight,
} from 'lucide-react'
import client, { formatErrorMessage } from '../api/client'

export default function Upload() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const queryVideoUrl = searchParams.get('video_url')
  const queryTitle = searchParams.get('title')

  const fileRef = useRef(null)
  const videoRef = useRef(null)
  const [file, setFile] = useState(null)
  const [videoUrl, setVideoUrl] = useState(null)
  const [remoteVideoUrl, setRemoteVideoUrl] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [channel, setChannel] = useState('')
  const [sheetRowId, setSheetRowId] = useState('')
  const [sheetRows, setSheetRows] = useState([])
  const [sheetPreview, setSheetPreview] = useState(null)
  const [sheetLoading, setSheetLoading] = useState(false)
  const [customTitle, setCustomTitle] = useState('')
  const [customDescription, setCustomDescription] = useState('')
  const [customTags, setCustomTags] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const [uploadPercent, setUploadPercent] = useState(null)
  const [sheetWarning, setSheetWarning] = useState('')
  const [videoDuration, setVideoDuration] = useState(null)
  const [videoReady, setVideoReady] = useState(false)

  const [channelsList, setChannelsList] = useState([])

  // Load from query params if opened from extension / Google Flow
  useEffect(() => {
    if (queryVideoUrl) {
      const decodedUrl = decodeURIComponent(queryVideoUrl)
      setRemoteVideoUrl(decodedUrl)
      setVideoUrl(decodedUrl)
      if (queryTitle) {
        setCustomTitle(decodeURIComponent(queryTitle))
      }

      // Attempt to download blob directly for standard multipart submission
      fetch(decodedUrl)
        .then(res => {
          if (!res.ok) throw new Error('CORS or network error')
          return res.blob()
        })
        .then(blob => {
          const f = new File([blob], 'flow_video.mp4', { type: blob.type || 'video/mp4' })
          setFile(f)
        })
        .catch(() => {
          // Direct blob fetch blocked by CORS, will use remote URL ingest
        })
    }
  }, [queryVideoUrl, queryTitle])

  useEffect(() => {
    client.get('/channels')
      .then(res => {
        if (Array.isArray(res.data) && res.data.length > 0) {
          const list = res.data.map(c => ({ id: c.channel, name: c.display_name || c.channel }))
          setChannelsList(list)
          if (!channel || !list.some(c => c.id === channel)) {
            setChannel(list[0].id)
          }
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (channel) {
      loadSheetRows()
      fetchSheetPreview(sheetRowId)
    }
  }, [channel])

  // Create / revoke object URL when file changes
  useEffect(() => {
    if (file) {
      const url = URL.createObjectURL(file)
      setVideoUrl(url)
      setVideoReady(false)
      setVideoDuration(null)
      return () => URL.revokeObjectURL(url)
    } else {
      setVideoUrl(null)
      setVideoReady(false)
      setVideoDuration(null)
    }
  }, [file])

  async function loadSheetRows() {
    setSheetWarning('')
    try {
      const res = await client.get(`/posts/sheet-rows?channel=${channel}`)
      if (res.data?.found && Array.isArray(res.data.rows) && res.data.rows.length > 0) {
        setSheetRows(res.data.rows)
      } else {
        setSheetRows([])
        if (res.data?.message) {
          setSheetWarning(`Google Sheets connection warning: ${res.data.message}`)
        }
      }
    } catch (e) {
      setSheetRows([])
      setSheetWarning('Google Sheets unreachable. Auto-detection will operate offline.')
    }
  }

  async function fetchSheetPreview(rowId) {
    setSheetLoading(true)
    try {
      const q = rowId && String(rowId).trim() ? `&row_id=${encodeURIComponent(String(rowId).trim())}` : ''
      const res = await client.get(`/posts/sheet-row?channel=${channel}${q}`)
      if (res.data?.found) {
        setSheetPreview(res.data)
        setCustomTitle(res.data.title || '')
        setCustomDescription(res.data.description || '')
        setCustomTags(res.data.tags || '')
      } else {
        setSheetPreview(null)
      }
    } catch (e) {
      setSheetPreview(null)
    }
    setSheetLoading(false)
  }

  function handleSelectRow(selectedId) {
    setSheetRowId(selectedId)
    fetchSheetPreview(selectedId)
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f && f.type.startsWith('video/')) setFile(f)
  }

  function handleFileChange(e) {
    const f = e.target.files[0]
    if (f) setFile(f)
  }

  function handleVideoLoaded(e) {
    const vid = e.target
    setVideoReady(true)
    if (vid.duration && isFinite(vid.duration)) {
      setVideoDuration(vid.duration)
    }
  }

  function fmtDuration(secs) {
    if (!secs || !isFinite(secs)) return ''
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!file && !videoUrl && !remoteVideoUrl) {
      setError('Please select a video file to upload.')
      return
    }

    setError('')
    setLoading(true)
    setUploadPercent(0)
    setProgress('Uploading video to server...')

    if (file) {
      const fd = new FormData()
      fd.append('video', file)
      fd.append('channel', channel)
      if (sheetRowId && String(sheetRowId).trim()) {
        fd.append('sheet_row_id', String(sheetRowId).trim())
      }
      if (customTitle.trim()) {
        fd.append('title', customTitle.trim())
      }
      if (customDescription.trim()) {
        fd.append('description', customDescription.trim())
      }
      if (customTags.trim()) {
        fd.append('tags', customTags.trim())
      }

      try {
        const res = await client.post('/posts', fd, {
          onUploadProgress: (progressEvent) => {
            if (progressEvent.total) {
              const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
              setUploadPercent(percentCompleted)
              if (percentCompleted < 100) {
                setProgress(`Uploading: ${percentCompleted}% (${fmtSize(progressEvent.loaded)} of ${fmtSize(progressEvent.total)})`)
              } else {
                setProgress('Upload completed. Initializing pipeline...')
              }
            }
          },
        })
        setProgress('Video ingested! Redirecting to post detail...')
        setTimeout(() => {
          navigate(`/post/${res.data.id}`)
        }, 600)
      } catch (err) {
        setError(formatErrorMessage(err))
        setProgress('')
        setUploadPercent(null)
        setLoading(false)
      }
    } else {
      // Remote video URL ingest
      try {
        setProgress('Ingesting video from Google Flow to pipeline...')
        const targetUrl = remoteVideoUrl || videoUrl
        const res = await client.post('/extension/ingest', {
          video_url: targetUrl,
          title: customTitle.trim() || 'Google Flow Video',
          channel: channel,
          description: customDescription.trim() || '',
          tags: customTags.trim() || '',
          sheet_row_id: sheetRowId ? String(sheetRowId).trim() : null,
        })
        setProgress('Video ingested! Redirecting to post detail...')
        setTimeout(() => {
          navigate(`/post/${res.data.post_id}`)
        }, 600)
      } catch (err) {
        setError(formatErrorMessage(err))
        setProgress('')
        setUploadPercent(null)
        setLoading(false)
      }
    }
  }

  function fmtSize(bytes) {
    if (!bytes) return ''
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div style={{ maxWidth: 780 }}>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">
            <UploadIcon size={22} color="var(--accent-primary)" />
            Upload Video
          </h1>
          <div className="page-subtitle">
            Ingest raw video files. Titles, descriptions, and tags will automatically sync from the selected Google Sheet row.
          </div>
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        {/* Drag & Drop Area */}
        <div
          style={{
            backgroundColor: 'var(--bg-card)',
            border: `2px dashed ${dragOver ? 'var(--accent-primary)' : 'var(--border-medium)'}`,
            borderRadius: 12,
            padding: (file || videoUrl) ? 16 : '48px 24px',
            textAlign: 'center',
            cursor: (file || videoUrl) ? 'default' : 'pointer',
            transition: 'all var(--transition-fast)',
            marginBottom: 20,
          }}
          onDragOver={e => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => !file && !videoUrl && fileRef.current?.click()}
          id="video-dropzone"
        >
          {(file || videoUrl) ? (
            <div>
              <div style={{ borderRadius: 8, overflow: 'hidden', backgroundColor: '#000', marginBottom: 12 }}>
                <video
                  ref={videoRef}
                  src={videoUrl}
                  controls
                  muted
                  playsInline
                  onLoadedMetadata={handleVideoLoaded}
                  style={{
                    width: '100%',
                    maxHeight: 320,
                    display: 'block',
                  }}
                />
              </div>

              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                backgroundColor: 'var(--bg-elevated)',
                padding: '10px 14px',
                borderRadius: 8,
                border: '1px solid var(--border-subtle)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left', minWidth: 0 }}>
                  <FileVideo size={20} color="var(--accent-primary)" />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13 }} className="truncate-text">
                      {file ? file.name : (customTitle || 'Google Flow Video')}
                    </div>
                    <div style={{ color: 'var(--text-muted)', fontSize: 11, display: 'flex', gap: 8, marginTop: 2 }}>
                      {file && <span>{fmtSize(file.size)}</span>}
                      {remoteVideoUrl && !file && <span style={{ color: 'var(--info)' }}>Google Flow Cloud Video</span>}
                      {videoDuration && <span>• {fmtDuration(videoDuration)}</span>}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={e => { e.stopPropagation(); setFile(null); setVideoUrl(null); setRemoteVideoUrl(''); }}
                  className="btn btn-ghost btn-sm btn-icon"
                  title="Remove video"
                >
                  <X size={15} />
                </button>
              </div>
            </div>
          ) : (
            <div>
              <div style={{
                width: 52,
                height: 52,
                borderRadius: 12,
                backgroundColor: 'var(--bg-elevated)',
                border: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px',
                color: 'var(--accent-primary)',
              }}>
                <UploadIcon size={24} />
              </div>
              <div style={{ color: 'var(--text-primary)', fontSize: 14.5, fontWeight: 600, marginBottom: 4 }}>
                Drag &amp; drop video here, or click to browse
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                Supports MP4, MOV, AVI, MKV up to 500MB
              </div>
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            accept="video/*"
            style={{ display: 'none' }}
            onChange={handleFileChange}
            id="video-file-input"
          />
        </div>

        {/* Configuration Card */}
        <div className="card" style={{ padding: 24, marginBottom: 20 }}>
          <div className="section-title">
            <Tv2 size={16} color="var(--accent-primary)" />
            Target Channel &amp; Google Sheet Row Binding
          </div>

          {/* Channel Selector */}
          <div className="form-group">
            <label className="form-label">Destination Channel</label>
            {channelsList.length === 0 ? (
              <div className="error-pill">
                No connected channels found. Please configure a channel in <a href="/channels">Channels</a> first.
              </div>
            ) : (
              <div className="tabs-nav" style={{ width: 'fit-content' }}>
                {channelsList.map(c => (
                  <button
                    key={c.id}
                    type="button"
                    className={`tab-item ${channel === c.id ? 'active' : ''}`}
                    onClick={() => setChannel(c.id)}
                    id={`channel-pick-${c.id}`}
                  >
                    {c.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Google Sheet Row Selector */}
          <div className="form-group" style={{ marginTop: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label className="form-label" style={{ margin: 0 }}>
                Select Google Sheet Row to Bind &amp; Update
              </label>
              <button
                type="button"
                onClick={() => { loadSheetRows(); fetchSheetPreview(sheetRowId); }}
                className="btn btn-ghost btn-sm"
                style={{ height: 24, fontSize: 11 }}
              >
                <RefreshCw size={11} className={sheetLoading ? 'spinner' : ''} />
                <span>Refresh Sheet</span>
              </button>
            </div>

            {sheetRows.length > 0 ? (
              <select
                id="upload-sheet-select"
                className="form-input"
                value={sheetRowId}
                onChange={e => handleSelectRow(e.target.value)}
                style={{ cursor: 'pointer', fontWeight: 500 }}
              >
                <option value="">🟢 Auto-Pick: Next Unscheduled Row in Sheet</option>
                {sheetRows.map(r => (
                  <option key={r.id} value={r.id}>
                    {r.is_scheduled ? '✓' : '•'} Row #{r.id}: {r.title ? (r.title.length > 65 ? r.title.slice(0, 65) + '...' : r.title) : '(Untitled)'} {r.is_scheduled ? `[Scheduled: ${r.scheduled}]` : '[Unscheduled]'}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="upload-sheet-id"
                className="form-input"
                type="text"
                placeholder="e.g. 12 (leave blank for automatic next unscheduled item)"
                value={sheetRowId}
                onChange={e => handleSelectRow(e.target.value)}
              />
            )}
            <div className="form-hint">
              {sheetRowId
                ? `⚡ Exact row #${sheetRowId} selected. AI enrichment, YouTube upload ID, and schedule time will update specifically on row #${sheetRowId}.`
                : '⚡ Auto-Pick active: The pipeline will select the first unscheduled row in your sheet and update that row upon upload.'}
            </div>
          </div>

          {/* Sheet Metadata Preview & Edit */}
          <div style={{
            backgroundColor: 'var(--bg-subtle)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 10,
            padding: 16,
            marginTop: 16,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--info)', fontSize: 12, fontWeight: 600 }}>
                <FileSpreadsheet size={15} />
                <span>Google Sheet Metadata {sheetPreview?.id ? `(Row #${sheetPreview.id})` : '(Auto-Pick Next Row)'}</span>
              </div>
              {sheetPreview?.scheduled && (
                <span className="badge badge-warning" style={{ fontSize: 10.5 }}>
                  Already Scheduled
                </span>
              )}
            </div>

            {sheetPreview?.scheduled && (
              <div style={{ padding: '8px 12px', borderRadius: 6, backgroundColor: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.3)', color: '#f59e0b', fontSize: 11.5, marginBottom: 12 }}>
                ℹ️ <strong>Note:</strong> Row #{sheetPreview.id} was already scheduled ({sheetPreview.scheduled}). Uploading this video will automatically create a <strong>new row with a fresh ID</strong> in your Google Sheet with these details.
              </div>
            )}

            {sheetLoading ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', fontSize: 12 }}>
                <span className="spinner" /> Fetching row metadata from Google Sheet...
              </div>
            ) : sheetPreview ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div>
                  <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                    Title (From Sheet Row #{sheetPreview.id})
                  </label>
                  <input
                    className="form-input"
                    value={customTitle}
                    onChange={e => setCustomTitle(e.target.value)}
                    placeholder="Enter or edit video title"
                  />
                </div>

                <div>
                  <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                    Description
                  </label>
                  <textarea
                    className="form-textarea"
                    rows={2}
                    value={customDescription}
                    onChange={e => setCustomDescription(e.target.value)}
                    placeholder="Video description"
                  />
                </div>

                <div>
                  <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                    Tags (semicolon-separated)
                  </label>
                  <input
                    className="form-input mono"
                    style={{ fontSize: 11.5 }}
                    value={customTags}
                    onChange={e => setCustomTags(e.target.value)}
                    placeholder="e.g. asmr; cooking; miniature food"
                  />
                </div>
              </div>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                Auto-detection mode active: Next available unscheduled row will be automatically selected upon upload.
              </div>
            )}
          </div>

          {sheetWarning && (
            <div className="card" style={{ marginTop: 16, padding: '10px 14px', backgroundColor: 'rgba(245, 185, 66, 0.08)', border: '1px solid rgba(245, 185, 66, 0.25)', color: 'var(--warning)', fontSize: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                <AlertCircle size={14} /> Google Sheets Notice
              </div>
              <div style={{ marginTop: 3, opacity: 0.9 }}>{sheetWarning}</div>
            </div>
          )}

          {error && (
            <div className="error-pill" style={{ marginTop: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                <AlertCircle size={14} /> Error
              </div>
              <div style={{ marginTop: 4 }}>{error}</div>
            </div>
          )}

          {progress && (
            <div style={{ marginTop: 16, backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: uploadPercent !== null ? 8 : 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 500 }}>
                  <span className="spinner" /> {progress}
                </div>
                {uploadPercent !== null && (
                  <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent-primary)' }}>
                    {uploadPercent}%
                  </span>
                )}
              </div>
              {uploadPercent !== null && (
                <div style={{ width: '100%', height: 6, backgroundColor: 'var(--bg-subtle)', borderRadius: 4, overflow: 'hidden' }}>
                  <div
                    style={{
                      height: '100%',
                      width: `${uploadPercent}%`,
                      backgroundColor: 'var(--accent-primary)',
                      borderRadius: 4,
                      transition: 'width 0.2s ease-in-out',
                    }}
                  />
                </div>
              )}
            </div>
          )}

          <div style={{ marginTop: 24 }}>
            <button
              type="submit"
              className="btn btn-primary btn-lg"
              disabled={loading}
              id="upload-submit"
              style={{ width: '100%', justifyContent: 'center' }}
            >
              {loading ? <span className="spinner" /> : <UploadIcon size={16} />}
              <span>{loading ? 'Ingesting Video...' : 'Start Pipeline Ingest'}</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
