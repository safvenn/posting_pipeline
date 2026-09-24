import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  Layers,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  RotateCcw,
  RefreshCw,
  Clock,
  Zap,
  Server,
  KeyRound,
  CheckCircle2,
  XCircle,
  Play,
  StopCircle,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Search,
  Filter,
  Lock,
  Cpu,
} from 'lucide-react'
import {
  useMetricsQuery,
  useJobStatsQuery,
  useJobsQuery,
  useCircuitBreakerQuery,
  useResetCircuitBreaker,
  useRequeueDeadLetters,
  useRetryJob,
  useCancelJob,
  useSecurityStatusQuery,
  useRotateSecret,
} from '../hooks/useOperations'
import { formatErrorMessage } from '../api/client'

function formatUptime(seconds) {
  if (!seconds && seconds !== 0) return '—'
  const s = Math.floor(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m ${sec}s`
  return `${m}m ${sec}s`
}

function formatDuration(ms) {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatIso(isoStr) {
  if (!isoStr) return '—'
  try {
    const d = new Date(isoStr)
    return d.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    })
  } catch {
    return isoStr
  }
}

export default function Operations() {
  const [activeTab, setActiveTab] = useState('metrics') // 'metrics' | 'jobs' | 'security'
  const [autoRefreshInterval, setAutoRefreshInterval] = useState(5000) // 5s default
  
  // Jobs filters
  const [jobStatusFilter, setJobStatusFilter] = useState('all')
  const [jobTypeFilter, setJobTypeFilter] = useState('all')
  const [postIdFilter, setPostIdFilter] = useState('')
  const [page, setPage] = useState(1)
  const [selectedJob, setSelectedJob] = useState(null)
  const [actionMessage, setActionMessage] = useState(null)

  // Secret rotation dialog
  const [isRotateModalOpen, setIsRotateModalOpen] = useState(false)
  const [customSecret, setCustomSecret] = useState('')
  const [rotationResult, setRotationResult] = useState(null)

  // React Query Hooks
  const {
    data: metrics,
    isLoading: metricsLoading,
    isFetching: metricsFetching,
    refetch: refetchMetrics,
  } = useMetricsQuery({ refetchInterval: autoRefreshInterval || false })

  const {
    data: jobStats,
    isLoading: statsLoading,
    refetch: refetchJobStats,
  } = useJobStatsQuery({ refetchInterval: autoRefreshInterval || false })

  const jobsParams = {
    page,
    page_size: 15,
    ...(jobStatusFilter !== 'all' ? { status: jobStatusFilter } : {}),
    ...(jobTypeFilter !== 'all' ? { job_type: jobTypeFilter } : {}),
    ...(postIdFilter.trim() ? { post_id: parseInt(postIdFilter.trim(), 10) } : {}),
  }

  const {
    data: jobsData,
    isLoading: jobsLoading,
    isFetching: jobsFetching,
    refetch: refetchJobs,
  } = useJobsQuery(jobsParams, { refetchInterval: autoRefreshInterval || false })

  const { data: circuitBreaker, refetch: refetchCircuitBreaker } = useCircuitBreakerQuery()
  const { data: securityStatus, isLoading: securityLoading, refetch: refetchSecurity } = useSecurityStatusQuery()

  // Mutations
  const resetCircuitBreakerMutation = useResetCircuitBreaker()
  const requeueDeadLettersMutation = useRequeueDeadLetters()
  const retryJobMutation = useRetryJob()
  const cancelJobMutation = useCancelJob()
  const rotateSecretMutation = useRotateSecret()

  const handleManualRefreshAll = () => {
    refetchMetrics()
    refetchJobStats()
    refetchJobs()
    refetchCircuitBreaker()
    refetchSecurity()
  }

  const handleResetCircuitBreaker = async () => {
    try {
      const res = await resetCircuitBreakerMutation.mutateAsync()
      setActionMessage({ type: 'success', text: res.message || 'Circuit breaker reset successfully!' })
      setTimeout(() => setActionMessage(null), 4000)
    } catch (err) {
      setActionMessage({ type: 'error', text: formatErrorMessage(err) })
    }
  }

  const handleRequeueDeadLetters = async () => {
    if (!window.confirm('Are you sure you want to requeue all Dead-Letter jobs?')) return
    try {
      const res = await requeueDeadLettersMutation.mutateAsync()
      setActionMessage({ type: 'success', text: `Requeued ${res.requeued_count} dead-letter jobs!` })
      setTimeout(() => setActionMessage(null), 4000)
    } catch (err) {
      setActionMessage({ type: 'error', text: formatErrorMessage(err) })
    }
  }

  const handleRetrySingleJob = async (jobId) => {
    try {
      await retryJobMutation.mutateAsync(jobId)
      setActionMessage({ type: 'success', text: `Job #${jobId} requeued for retry.` })
      setTimeout(() => setActionMessage(null), 3000)
    } catch (err) {
      setActionMessage({ type: 'error', text: formatErrorMessage(err) })
    }
  }

  const handleCancelSingleJob = async (jobId) => {
    if (!window.confirm(`Cancel non-terminal Job #${jobId}?`)) return
    try {
      await cancelJobMutation.mutateAsync(jobId)
      setActionMessage({ type: 'success', text: `Job #${jobId} cancelled.` })
      setTimeout(() => setActionMessage(null), 3000)
    } catch (err) {
      setActionMessage({ type: 'error', text: formatErrorMessage(err) })
    }
  }

  const handleExecuteRotateSecret = async () => {
    if (!window.confirm('WARNING: Rotating the JWT secret revokes ALL active sessions immediately. Proceed?')) return
    try {
      const res = await rotateSecretMutation.mutateAsync(customSecret.trim() || undefined)
      setRotationResult(res)
      setCustomSecret('')
    } catch (err) {
      setActionMessage({ type: 'error', text: formatErrorMessage(err) })
    }
  }

  const isFetchingAny = metricsFetching || jobsFetching

  return (
    <div className="page-container" style={{ paddingBottom: 40 }}>
      {/* ── Page Header ────────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 16,
        marginBottom: 24,
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              backgroundColor: 'var(--color-primary)',
              color: '#FFFFFF',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: 'var(--shadow-sm)',
            }}>
              <Activity size={20} />
            </div>
            <div>
              <h1 style={{
                fontSize: 22,
                fontWeight: 700,
                color: 'var(--text-primary)',
                letterSpacing: '-0.02em',
                lineHeight: 1.2,
              }}>
                Operations & Telemetry
              </h1>
              <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>
                Live pipeline observability, job execution engine, and security telemetry.
              </p>
            </div>
          </div>
        </div>

        {/* Global Controls: Auto-refresh & Manual trigger */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'var(--bg-input)',
            borderRadius: 8,
            border: '1px solid var(--border-subtle)',
            padding: '4px 8px',
            fontSize: 12,
            gap: 6,
          }}>
            <span style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor: autoRefreshInterval ? 'var(--success)' : 'var(--text-muted)',
              display: 'inline-block',
              animation: autoRefreshInterval ? 'pulse 2s infinite' : 'none',
            }} />
            <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>Live Poll:</span>
            <select
              value={autoRefreshInterval}
              onChange={(e) => setAutoRefreshInterval(Number(e.target.value))}
              style={{
                border: 'none',
                background: 'transparent',
                fontWeight: 600,
                color: 'var(--text-primary)',
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              <option value={0}>Off</option>
              <option value={3000}>3s (Fast)</option>
              <option value={5000}>5s (Normal)</option>
              <option value={15000}>15s (Eco)</option>
            </select>
          </div>

          <button
            onClick={handleManualRefreshAll}
            disabled={isFetchingAny}
            className="btn btn-secondary"
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '7px 12px' }}
          >
            <RefreshCw size={14} className={isFetchingAny ? 'spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* ── Global Alert Banner ────────────────────────────────── */}
      {actionMessage && (
        <div style={{
          padding: '12px 16px',
          borderRadius: 8,
          marginBottom: 20,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          backgroundColor: actionMessage.type === 'error' ? 'var(--error-subtle)' : 'var(--success-subtle)',
          color: actionMessage.type === 'error' ? 'var(--error)' : 'var(--success)',
          border: `1px solid ${actionMessage.type === 'error' ? 'var(--error-border)' : 'var(--success-border)'}`,
          fontSize: 13,
          fontWeight: 500,
        }}>
          {actionMessage.type === 'error' ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{actionMessage.text}</span>
        </div>
      )}

      {/* ── Navigation Tabs ────────────────────────────────────── */}
      <div style={{
        display: 'flex',
        gap: 8,
        borderBottom: '1px solid var(--border-subtle)',
        marginBottom: 24,
      }}>
        <button
          onClick={() => setActiveTab('metrics')}
          style={{
            padding: '10px 18px',
            fontSize: 13,
            fontWeight: 600,
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            color: activeTab === 'metrics' ? 'var(--color-primary)' : 'var(--text-muted)',
            borderBottom: activeTab === 'metrics' ? '2px solid var(--color-primary)' : '2px solid transparent',
            marginBottom: -1,
            transition: 'all 0.15s ease',
          }}
        >
          <Activity size={16} />
          <span>Telemetry & Metrics</span>
        </button>

        <button
          onClick={() => setActiveTab('jobs')}
          style={{
            padding: '10px 18px',
            fontSize: 13,
            fontWeight: 600,
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            color: activeTab === 'jobs' ? 'var(--color-primary)' : 'var(--text-muted)',
            borderBottom: activeTab === 'jobs' ? '2px solid var(--color-primary)' : '2px solid transparent',
            marginBottom: -1,
            transition: 'all 0.15s ease',
          }}
        >
          <Layers size={16} />
          <span>Job Queue & Fault Recovery</span>
          {jobStats?.dead_letter_count > 0 && (
            <span style={{
              backgroundColor: 'var(--error)',
              color: '#FFFFFF',
              fontSize: 11,
              padding: '1px 6px',
              borderRadius: 10,
              fontWeight: 700,
            }}>
              {jobStats.dead_letter_count}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('security')}
          style={{
            padding: '10px 18px',
            fontSize: 13,
            fontWeight: 600,
            border: 'none',
            background: 'none',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            color: activeTab === 'security' ? 'var(--color-primary)' : 'var(--text-muted)',
            borderBottom: activeTab === 'security' ? '2px solid var(--color-primary)' : '2px solid transparent',
            marginBottom: -1,
            transition: 'all 0.15s ease',
          }}
        >
          <ShieldCheck size={16} />
          <span>Security & Credentials</span>
        </button>
      </div>

      {/* ── TAB 1: METRICS & TELEMETRY ──────────────────────────── */}
      {activeTab === 'metrics' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* Top summary row */}
          <div className="stats-grid">
            <div className="stat-card">
              <div className="stat-icon" style={{ backgroundColor: 'var(--accent-subtle)', color: 'var(--color-primary)' }}>
                <Clock size={18} />
              </div>
              <div>
                <div className="stat-value">{formatUptime(metrics?.system?.uptime_seconds)}</div>
                <div className="stat-label">System Uptime</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ backgroundColor: 'var(--secondary-subtle)', color: 'var(--color-secondary)' }}>
                <Zap size={18} />
              </div>
              <div>
                <div className="stat-value">{metrics?.job_execution?.running_count ?? 0}</div>
                <div className="stat-label">Jobs Currently Running</div>
              </div>
            </div>

            <div className="stat-card">
              <div className="stat-icon" style={{ backgroundColor: 'var(--success-subtle)', color: 'var(--success)' }}>
                <CheckCircle2 size={18} />
              </div>
              <div>
                <div className="stat-value">{metrics?.job_execution?.succeeded_24h ?? 0}</div>
                <div className="stat-label">Succeeded (24h)</div>
              </div>
            </div>

            <div className="stat-card" style={metrics?.job_execution?.dead_letter_count > 0 ? { borderColor: 'var(--error-border)' } : {}}>
              <div className="stat-icon" style={{
                backgroundColor: metrics?.job_execution?.dead_letter_count > 0 ? 'var(--error-subtle)' : 'var(--bg-elevated)',
                color: metrics?.job_execution?.dead_letter_count > 0 ? 'var(--error)' : 'var(--text-muted)',
              }}>
                <AlertTriangle size={18} />
              </div>
              <div>
                <div className="stat-value" style={metrics?.job_execution?.dead_letter_count > 0 ? { color: 'var(--error)' } : {}}>
                  {metrics?.job_execution?.dead_letter_count ?? 0}
                </div>
                <div className="stat-label">Dead Letters (DLQ)</div>
              </div>
            </div>
          </div>

          {/* Pipeline Queue Stage Visualizer */}
          <div className="card" style={{ padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div>
                <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>Pipeline Queue Stages</h2>
                <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  Total active inventory: {metrics?.pipeline_queue?.total_posts ?? 0} posts
                </p>
              </div>
              <span style={{ fontSize: 11, color: 'var(--text-subtle)', fontFamily: 'var(--font-mono)' }}>
                Snapshot: {formatIso(metrics?.system?.collected_at)}
              </span>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
              gap: 12,
            }}>
              {[
                { label: 'Queued', count: metrics?.pipeline_queue?.queued_count ?? 0, color: 'var(--color-secondary)' },
                { label: 'Cleaning', count: metrics?.pipeline_queue?.cleaning_count ?? 0, color: 'var(--color-primary)' },
                { label: 'Cleaned', count: metrics?.pipeline_queue?.cleaned_count ?? 0, color: '#4B88A2' },
                { label: 'Scheduled', count: metrics?.pipeline_queue?.scheduled_count ?? 0, color: 'var(--warning)' },
                { label: 'Uploaded', count: metrics?.pipeline_queue?.uploaded_count ?? 0, color: 'var(--color-secondary)' },
                { label: 'Commented', count: metrics?.pipeline_queue?.commented_count ?? 0, color: 'var(--success)' },
                { label: 'Failed', count: metrics?.pipeline_queue?.failed_count ?? 0, color: 'var(--error)' },
              ].map((stage) => (
                <div
                  key={stage.label}
                  style={{
                    backgroundColor: 'var(--bg-app)',
                    borderRadius: 8,
                    padding: '12px 14px',
                    border: '1px solid var(--border-subtle)',
                    borderLeft: `4px solid ${stage.color}`,
                  }}
                >
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>
                    {stage.label}
                  </div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                    {stage.count}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Latency by Job Type (SLA Observability) */}
          <div className="card" style={{ padding: 20 }}>
            <div style={{ marginBottom: 16 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>Execution Latency & SLA (24h)</h2>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                p50 (median) and p95 (tail latency) percentiles aggregated per job type.
              </p>
            </div>

            {metrics?.job_execution?.latency_by_type && Object.keys(metrics.job_execution.latency_by_type).length > 0 ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
                {Object.entries(metrics.job_execution.latency_by_type).map(([jobType, lat]) => (
                  <div
                    key={jobType}
                    style={{
                      padding: 16,
                      borderRadius: 8,
                      backgroundColor: 'var(--bg-app)',
                      border: '1px solid var(--border-subtle)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                        {jobType}
                      </span>
                      <span style={{
                        fontSize: 11,
                        padding: '2px 8px',
                        borderRadius: 12,
                        backgroundColor: 'var(--bg-elevated)',
                        color: 'var(--text-secondary)',
                        fontFamily: 'var(--font-mono)',
                      }}>
                        {lat.sample_count} runs
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontSize: 12 }}>
                      <span style={{ color: 'var(--text-muted)' }}>Median (p50):</span>
                      <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                        {formatDuration(lat.p50_ms)}
                      </strong>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                      <span style={{ color: 'var(--text-muted)' }}>Tail (p95):</span>
                      <strong style={{ color: lat.p95_ms > 120000 ? 'var(--warning)' : 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                        {formatDuration(lat.p95_ms)}
                      </strong>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                No completed job executions recorded in the past 24 hours.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TAB 2: JOBS & DLQ RECOVERY ──────────────────────────── */}
      {activeTab === 'jobs' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Circuit Breaker & DLQ Recovery Banner */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 16,
          }}>
            {/* Circuit Breaker Card */}
            <div className="card" style={{
              padding: 18,
              borderLeft: `4px solid ${circuitBreaker?.tripped ? 'var(--error)' : 'var(--success)'}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {circuitBreaker?.tripped ? (
                    <ShieldAlert size={22} color="var(--error)" />
                  ) : (
                    <ShieldCheck size={22} color="var(--success)" />
                  )}
                  <div>
                    <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                      Circuit Breaker: {circuitBreaker?.tripped ? 'TRIPPED (PAUSED)' : 'HEALTHY'}
                    </h3>
                    <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {circuitBreaker?.message || 'Automatic queue safety valve'}
                    </p>
                  </div>
                </div>

                {circuitBreaker?.tripped && (
                  <button
                    onClick={handleResetCircuitBreaker}
                    disabled={resetCircuitBreakerMutation.isPending}
                    className="btn btn-primary"
                    style={{ fontSize: 12, padding: '6px 12px' }}
                  >
                    Reset Breaker
                  </button>
                )}
              </div>
            </div>

            {/* DLQ Bulk Requeue Card */}
            <div className="card" style={{ padding: 18, borderLeft: '4px solid var(--warning)' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                    Dead-Letter Queue (DLQ)
                  </h3>
                  <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {jobStats?.dead_letter_count ?? 0} jobs require operator intervention
                  </p>
                </div>

                <button
                  onClick={handleRequeueDeadLetters}
                  disabled={(jobStats?.dead_letter_count ?? 0) === 0 || requeueDeadLettersMutation.isPending}
                  className="btn btn-secondary"
                  style={{ fontSize: 12, padding: '6px 12px', display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  <RotateCcw size={13} />
                  <span>Requeue All DLQ</span>
                </button>
              </div>
            </div>
          </div>

          {/* Job Explorer Card */}
          <div className="card" style={{ padding: 20 }}>
            {/* Filter controls */}
            <div style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 12,
              marginBottom: 16,
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
                {/* Status select */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <span style={{ color: 'var(--text-muted)' }}>Status:</span>
                  <select
                    className="input"
                    value={jobStatusFilter}
                    onChange={(e) => {
                      setJobStatusFilter(e.target.value)
                      setPage(1)
                    }}
                    style={{ padding: '4px 8px', fontSize: 12, width: 130 }}
                  >
                    <option value="all">All Statuses</option>
                    <option value="pending">Pending</option>
                    <option value="running">Running</option>
                    <option value="succeeded">Succeeded</option>
                    <option value="failed">Failed</option>
                    <option value="dead_letter">Dead Letter</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>

                {/* Job type select */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <span style={{ color: 'var(--text-muted)' }}>Type:</span>
                  <select
                    className="input"
                    value={jobTypeFilter}
                    onChange={(e) => {
                      setJobTypeFilter(e.target.value)
                      setPage(1)
                    }}
                    style={{ padding: '4px 8px', fontSize: 12, width: 150 }}
                  >
                    <option value="all">All Types</option>
                    <option value="watermark_clean">watermark_clean</option>
                    <option value="upload_youtube">upload_youtube</option>
                    <option value="post_comment">post_comment</option>
                    <option value="cleanup">cleanup</option>
                  </select>
                </div>

                {/* Post ID Filter */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input
                    type="number"
                    className="input"
                    placeholder="Post ID..."
                    value={postIdFilter}
                    onChange={(e) => {
                      setPostIdFilter(e.target.value)
                      setPage(1)
                    }}
                    style={{ padding: '4px 8px', fontSize: 12, width: 100 }}
                  />
                </div>
              </div>

              {/* Total items badge */}
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Total: <strong>{jobsData?.total ?? 0}</strong> jobs
              </div>
            </div>

            {/* Jobs Table */}
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Job ID</th>
                    <th>Type</th>
                    <th>Post ID</th>
                    <th>Status</th>
                    <th>Attempt</th>
                    <th>Duration</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobsLoading ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>
                        <span className="spinner" style={{ width: 16, height: 16, display: 'inline-block', marginRight: 8 }} />
                        Loading jobs...
                      </td>
                    </tr>
                  ) : jobsData?.items?.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)' }}>
                        No jobs matched the current filters.
                      </td>
                    </tr>
                  ) : (
                    jobsData?.items?.map((job) => (
                      <tr key={job.id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                          #{job.id}
                        </td>
                        <td>
                          <span style={{
                            padding: '2px 6px',
                            borderRadius: 4,
                            backgroundColor: 'var(--bg-app)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: 11,
                          }}>
                            {job.job_type}
                          </span>
                        </td>
                        <td>
                          {job.post_id ? (
                            <Link
                              to={`/post/${job.post_id}`}
                              style={{ color: 'var(--color-primary)', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                            >
                              <span>#{job.post_id}</span>
                              <ExternalLink size={10} />
                            </Link>
                          ) : (
                            <span style={{ color: 'var(--text-subtle)' }}>—</span>
                          )}
                        </td>
                        <td>
                          <span className={`badge badge-${job.status}`} style={{
                            fontSize: 10,
                            padding: '2px 8px',
                            borderRadius: 10,
                            textTransform: 'uppercase',
                            fontWeight: 700,
                          }}>
                            {job.status}
                          </span>
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>
                          {job.attempt}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>
                          {formatDuration(job.duration_ms)}
                        </td>
                        <td style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                          {formatIso(job.created_at)}
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button
                              onClick={() => setSelectedJob(job)}
                              className="btn btn-ghost btn-sm"
                              style={{ padding: '2px 6px', fontSize: 11 }}
                              title="Inspect details"
                            >
                              Inspect
                            </button>
                            {(job.status === 'failed' || job.status === 'dead_letter') && (
                              <button
                                onClick={() => handleRetrySingleJob(job.id)}
                                className="btn btn-secondary btn-sm"
                                style={{ padding: '2px 6px', fontSize: 11 }}
                                title="Retry job"
                              >
                                Retry
                              </button>
                            )}
                            {!job.is_terminal && (
                              <button
                                onClick={() => handleCancelSingleJob(job.id)}
                                className="btn btn-ghost btn-sm"
                                style={{ padding: '2px 6px', fontSize: 11, color: 'var(--error)' }}
                                title="Cancel job"
                              >
                                Cancel
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination controls */}
            {jobsData && jobsData.pages > 1 && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginTop: 16,
                paddingTop: 12,
                borderTop: '1px solid var(--border-subtle)',
                fontSize: 12,
              }}>
                <span style={{ color: 'var(--text-muted)' }}>
                  Page {jobsData.page} of {jobsData.pages}
                </span>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="btn btn-ghost btn-sm"
                    style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                  >
                    <ChevronLeft size={14} />
                    <span>Prev</span>
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(jobsData.pages, p + 1))}
                    disabled={page >= jobsData.pages}
                    className="btn btn-ghost btn-sm"
                    style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                  >
                    <span>Next</span>
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TAB 3: SECURITY & CREDENTIAL HEALTH ─────────────────── */}
      {activeTab === 'security' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {securityLoading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
              <span className="spinner" style={{ width: 20, height: 20, display: 'inline-block', marginRight: 8 }} />
              Verifying credential and cipher configuration...
            </div>
          ) : (
            <>
              {/* Credentials & Cipher Grid */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                gap: 16,
              }}>
                {/* Service Account Card */}
                <div className="card" style={{ padding: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                    <div style={{
                      width: 32,
                      height: 32,
                      borderRadius: 6,
                      backgroundColor: securityStatus?.service_account?.configured ? 'var(--success-subtle)' : 'var(--error-subtle)',
                      color: securityStatus?.service_account?.configured ? 'var(--success)' : 'var(--error)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}>
                      <KeyRound size={18} />
                    </div>
                    <div>
                      <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Google Service Account</h3>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>YouTube & Drive API credentials</div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Status:</span>
                      <span style={{
                        fontWeight: 600,
                        color: securityStatus?.service_account?.configured ? 'var(--success)' : 'var(--error)',
                      }}>
                        {securityStatus?.service_account?.configured ? 'CONFIGURED' : 'MISSING'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Storage Source:</span>
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{securityStatus?.service_account?.source || 'none'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Fingerprint:</span>
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{securityStatus?.service_account?.fingerprint_prefix || '—'}</span>
                    </div>
                  </div>
                </div>

                {/* Data Encryption Card */}
                <div className="card" style={{ padding: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                    <div style={{
                      width: 32,
                      height: 32,
                      borderRadius: 6,
                      backgroundColor: securityStatus?.token_encryption?.encryption_enabled ? 'var(--success-subtle)' : 'var(--warning-subtle)',
                      color: securityStatus?.token_encryption?.encryption_enabled ? 'var(--success)' : 'var(--warning)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}>
                      <Lock size={18} />
                    </div>
                    <div>
                      <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>Data At Rest Encryption</h3>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Tokens and secrets storage cipher</div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Cipher Algorithm:</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                        {securityStatus?.token_encryption?.algorithm || 'AES-256-GCM'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Encryption Active:</span>
                      <span style={{
                        fontWeight: 600,
                        color: securityStatus?.token_encryption?.encryption_enabled ? 'var(--success)' : 'var(--warning)',
                      }}>
                        {securityStatus?.token_encryption?.encryption_enabled ? 'ENABLED' : 'DISABLED'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Rotation In Progress:</span>
                      <span>{securityStatus?.token_encryption?.rotation_in_progress ? 'Yes' : 'No'}</span>
                    </div>
                  </div>
                </div>

                {/* JWT Session Card */}
                <div className="card" style={{ padding: 20 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                    <div style={{
                      width: 32,
                      height: 32,
                      borderRadius: 6,
                      backgroundColor: securityStatus?.jwt?.secret_configured ? 'var(--accent-subtle)' : 'var(--error-subtle)',
                      color: securityStatus?.jwt?.secret_configured ? 'var(--color-primary)' : 'var(--error)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}>
                      <Cpu size={18} />
                    </div>
                    <div>
                      <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>JWT Session Security</h3>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Access & refresh token windows</div>
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Active Sessions:</span>
                      <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                        {securityStatus?.jwt?.active_sessions ?? 0}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Access Expiration:</span>
                      <span>{securityStatus?.jwt?.access_token_expire_minutes ?? 15} minutes</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Refresh Expiration:</span>
                      <span>{securityStatus?.jwt?.refresh_token_expire_days ?? 30} days</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Security Recommendations List */}
              <div className="card" style={{ padding: 20 }}>
                <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>
                  Automated Security Audit & Recommendations
                </h3>
                {securityStatus?.security_recommendations?.length === 0 ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--success)', fontSize: 13 }}>
                    <CheckCircle2 size={16} />
                    <span>All security health checks are passing! No actions required.</span>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {securityStatus?.security_recommendations?.map((rec, i) => (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 10,
                          padding: '10px 14px',
                          backgroundColor: 'var(--bg-app)',
                          borderRadius: 6,
                          fontSize: 12,
                          borderLeft: '3px solid var(--warning)',
                        }}
                      >
                        <AlertTriangle size={15} color="var(--warning)" style={{ flexShrink: 0, marginTop: 1 }} />
                        <span style={{ color: 'var(--text-primary)' }}>{rec}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* JWT Secret Rotation Console */}
              <div className="card" style={{ padding: 20, borderColor: 'var(--warning-border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                  <div>
                    <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
                      Zero-Downtime JWT Secret Rotation
                    </h3>
                    <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, maxWidth: 600 }}>
                      Rotates the active JWT secret and revokes all active refresh tokens. Users will be forced to re-authenticate.
                      Ensure the new secret is also persisted to your deployment environment variables.
                    </p>
                  </div>

                  <button
                    onClick={() => {
                      setRotationResult(null)
                      setIsRotateModalOpen(true)
                    }}
                    className="btn btn-secondary"
                    style={{ fontSize: 12, padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 6 }}
                  >
                    <KeyRound size={14} />
                    <span>Initiate Secret Rotation</span>
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── JOB INSPECT MODAL ───────────────────────────────────── */}
      {selectedJob && (
        <div style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(20, 41, 64, 0.65)',
          backdropFilter: 'blur(3px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 50,
          padding: 16,
        }}>
          <div className="card" style={{
            width: '100%',
            maxWidth: 600,
            maxHeight: '85vh',
            overflowY: 'auto',
            padding: 24,
            backgroundColor: 'var(--bg-card)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>
                  Job Execution Detail #{selectedJob.id}
                </h3>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  Type: {selectedJob.job_type}
                </span>
              </div>
              <button
                onClick={() => setSelectedJob(null)}
                className="btn btn-ghost btn-sm"
                style={{ fontSize: 16 }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
                <span style={{ color: 'var(--text-muted)' }}>Status:</span>
                <span className={`status-badge status-${selectedJob.status}`}>{selectedJob.status}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
                <span style={{ color: 'var(--text-muted)' }}>Post ID:</span>
                <span>{selectedJob.post_id ? `#${selectedJob.post_id}` : 'None'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
                <span style={{ color: 'var(--text-muted)' }}>Attempt:</span>
                <span>{selectedJob.attempt}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
                <span style={{ color: 'var(--text-muted)' }}>Duration:</span>
                <span>{formatDuration(selectedJob.duration_ms)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
                <span style={{ color: 'var(--text-muted)' }}>Scheduled At:</span>
                <span>{formatIso(selectedJob.scheduled_at)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
                <span style={{ color: 'var(--text-muted)' }}>Started At:</span>
                <span>{formatIso(selectedJob.started_at)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
                <span style={{ color: 'var(--text-muted)' }}>Finished At:</span>
                <span>{formatIso(selectedJob.finished_at)}</span>
              </div>

              {selectedJob.error_message && (
                <div>
                  <span style={{ color: 'var(--error)', fontWeight: 600 }}>Error Message:</span>
                  <div style={{
                    marginTop: 6,
                    padding: 10,
                    borderRadius: 6,
                    backgroundColor: 'var(--error-subtle)',
                    color: 'var(--error)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}>
                    {selectedJob.error_message}
                  </div>
                </div>
              )}

              {selectedJob.output && (
                <div>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>Output Payload:</span>
                  <pre style={{
                    marginTop: 6,
                    padding: 10,
                    borderRadius: 6,
                    backgroundColor: 'var(--bg-app)',
                    color: 'var(--text-primary)',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    overflowX: 'auto',
                  }}>
                    {JSON.stringify(selectedJob.output, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
              <button onClick={() => setSelectedJob(null)} className="btn btn-secondary btn-sm">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── ROTATE SECRET MODAL ─────────────────────────────────── */}
      {isRotateModalOpen && (
        <div style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(20, 41, 64, 0.65)',
          backdropFilter: 'blur(3px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 50,
          padding: 16,
        }}>
          <div className="card" style={{
            width: '100%',
            maxWidth: 520,
            padding: 24,
            backgroundColor: 'var(--bg-card)',
          }}>
            <h3 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
              JWT Secret Rotation
            </h3>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
              This will immediately revoke all active refresh tokens and replace the in-memory signing secret.
            </p>

            {rotationResult ? (
              <div style={{
                padding: 16,
                borderRadius: 8,
                backgroundColor: 'var(--success-subtle)',
                border: '1px solid var(--success-border)',
                marginBottom: 16,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--success)', fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
                  <CheckCircle2 size={16} />
                  <span>{rotationResult.detail}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-primary)', display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div>Sessions Revoked: <strong>{rotationResult.sessions_revoked}</strong></div>
                  <div>New Secret Prefix: <code style={{ fontFamily: 'var(--font-mono)' }}>{rotationResult.new_secret_preview}...</code></div>
                  <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                    Don't forget to update your Render environment variable <code style={{ fontFamily: 'var(--font-mono)' }}>JWT_SECRET</code> before next deployment.
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
                <div>
                  <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', display: 'block', marginBottom: 4 }}>
                    Custom Secret (optional - leave empty to auto-generate 64-char hex):
                  </label>
                  <input
                    type="password"
                    className="input"
                    placeholder="Auto-generate cryptographically secure key"
                    value={customSecret}
                    onChange={(e) => setCustomSecret(e.target.value)}
                    style={{ width: '100%', fontSize: 12 }}
                  />
                </div>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button
                onClick={() => {
                  setIsRotateModalOpen(false)
                  setRotationResult(null)
                }}
                className="btn btn-ghost btn-sm"
              >
                {rotationResult ? 'Done' : 'Cancel'}
              </button>
              {!rotationResult && (
                <button
                  onClick={handleExecuteRotateSecret}
                  disabled={rotateSecretMutation.isPending}
                  className="btn btn-primary btn-sm"
                  style={{ backgroundColor: 'var(--error)', borderColor: 'var(--error)' }}
                >
                  {rotateSecretMutation.isPending ? 'Rotating...' : 'Rotate Secret Now'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
