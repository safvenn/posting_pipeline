import React, { useState, useEffect } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  Calendar,
  Tv2,
  AlertTriangle,
  Terminal,
  Sparkles,
  RefreshCw,
  LogOut,
  X,
} from 'lucide-react'
import { usePostsQuery } from '../hooks/usePosts'
import { useChannelsQuery } from '../hooks/useChannels'
import { useAuth } from '../context/AuthContext'

export default function Sidebar({ isOpen, onClose }) {
  const [time, setTime] = useState('')
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  const { data: postData } = usePostsQuery()
  const { data: channels = [] } = useChannelsQuery()

  const posts = postData?.items || []
  const scheduledCount = posts.filter(p => ['scheduled', 'uploaded'].includes(p.status)).length
  const failedCount = posts.filter(p => p.status === 'failed').length

  useEffect(() => {
    function updateClock() {
      const now = new Date()
      setTime(now.toLocaleTimeString('en-US', {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
      }))
    }
    updateClock()
    const timer = setInterval(updateClock, 1000)
    return () => clearInterval(timer)
  }, [])

  const navCls = ({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`

  return (
    <>
      {isOpen && (
        <div
          onClick={onClose}
          style={{
            position: 'fixed', inset: 0,
            background: 'rgba(5, 7, 10, 0.7)',
            backdropFilter: 'blur(3px)',
            zIndex: 35,
          }}
        />
      )}

      <aside className={`sidebar${isOpen ? ' open' : ''}`}>

        <div className="sidebar-logo">
          <div className="flex items-center gap-2.5">
            <div className="relative w-7 h-7 rounded-lg bg-surface-2 border border-border-strong flex items-center justify-center flex-shrink-0">
              <Terminal size={13} className="text-primary" />
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-status-success ring-1" style={{ '--tw-ring-color': 'var(--bg-subtle)' }} />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <h1 className="text-sm font-bold text-on-surface tracking-tight">YT Pipeline</h1>
                <span className="text-[10px] font-mono px-1 py-0.5 rounded text-outline border border-border-subtle" style={{ backgroundColor: 'var(--bg-elevated)' }}>
                  v2.4
                </span>
              </div>
              <p className="text-[10.5px] text-outline mt-0.5">Auto-publish · 2 channels</p>
            </div>
          </div>

          {onClose && (
            <button
              onClick={onClose}
              className="md:hidden p-1 rounded-md text-outline hover:text-on-surface transition-colors"
              style={{ ':hover': { backgroundColor: 'var(--bg-elevated)' } }}
              aria-label="Close sidebar"
            >
              <X size={15} />
            </button>
          )}
        </div>

        <nav className="sidebar-nav">

          <button
            className="btn btn-primary w-full justify-center mb-2"
            onClick={() => { navigate('/upload'); if (onClose) onClose() }}
          >
            <Upload size={13} />
            <span>Upload Video</span>
          </button>

          <div className="sidebar-nav-section">Pipeline</div>

          <NavLink to="/" end onClick={onClose} className={navCls}>
            <LayoutDashboard size={14} />
            <span>Dashboard</span>
          </NavLink>

          <NavLink to="/upload" onClick={onClose} className={navCls}>
            <Upload size={14} />
            <span>Upload Video</span>
          </NavLink>

          <NavLink to="/schedule" onClick={onClose} className={({ isActive }) =>
            `sidebar-nav-item justify-between${isActive ? ' active' : ''}`
          }>
            <div className="flex items-center gap-2">
              <Calendar size={14} />
              <span>Schedule</span>
            </div>
            {scheduledCount > 0 && (
              <span className="text-[10px] font-mono text-on-surface-variant px-1.5 py-0.5 rounded border border-border-subtle flex-shrink-0" style={{ backgroundColor: 'var(--bg-elevated)' }}>
                {scheduledCount}
              </span>
            )}
          </NavLink>

          <div className="sidebar-nav-section" style={{ marginTop: 6 }}>Automation</div>

          <NavLink to="/asmr" onClick={onClose} className={navCls}>
            <Sparkles size={14} />
            <span>ASMR Studio</span>
          </NavLink>

          <NavLink to="/channels" onClick={onClose} className={({ isActive }) =>
            `sidebar-nav-item justify-between${isActive ? ' active' : ''}`
          }>
            <div className="flex items-center gap-2">
              <Tv2 size={14} />
              <span>Channels</span>
            </div>
            <span className="text-[10.5px] font-mono text-outline flex-shrink-0">{channels.length} live</span>
          </NavLink>

          <div className="sidebar-nav-section" style={{ marginTop: 6 }}>System</div>

          <NavLink to="/failed" onClick={onClose} className={({ isActive }) =>
            `sidebar-nav-item justify-between${isActive ? ' active' : ''}`
          }>
            <div className="flex items-center gap-2">
              <AlertTriangle size={14} className={failedCount > 0 ? 'text-status-danger' : ''} />
              <span className={failedCount > 0 ? 'text-status-danger' : ''}>Failed Jobs</span>
            </div>
            {failedCount > 0 && (
              <span className="text-[10px] font-mono text-status-danger px-1.5 py-0.5 rounded font-semibold flex-shrink-0"
                style={{ backgroundColor: 'var(--error-subtle)', border: '1px solid var(--error-border)' }}>
                {failedCount}
              </span>
            )}
          </NavLink>

        </nav>

        <div className="sidebar-footer">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5" style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
              <span className="w-1.5 h-1.5 rounded-full bg-status-success flex-shrink-0" style={{ backgroundColor: 'var(--success)' }} />
              <span className="font-medium">IST</span>
            </div>
            <span className="font-mono font-semibold tabular-nums" style={{ fontSize: 12, color: 'var(--text-primary)' }}>
              {time || '—'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5" style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
              <RefreshCw size={11} className="text-primary animate-spin" style={{ animationDuration: '4s' }} />
              <span>Auto-refresh</span>
            </div>
            <span className="font-mono font-medium" style={{ fontSize: 11.5, color: 'var(--accent-primary)' }}>15s</span>
          </div>

          <div
            className="pt-2 mt-2 flex items-center justify-between"
            style={{ borderTop: '1px solid var(--border-subtle)' }}
          >
            <div className="flex items-center gap-2 min-w-0">
              <div
                className="w-5 h-5 rounded-full flex items-center justify-center font-bold text-[10px] flex-shrink-0"
                style={{
                  backgroundColor: 'var(--accent-subtle)',
                  color: 'var(--accent-primary)',
                  border: '1px solid var(--accent-border)',
                }}
              >
                {(user || 'adminn').charAt(0).toUpperCase()}
              </div>
              <span className="truncate font-mono text-[11.5px]" style={{ color: 'var(--text-secondary)' }}>
                {user || 'adminn'}
              </span>
            </div>
            <button
              onClick={() => {
                logout()
                if (onClose) onClose()
              }}
              title="Sign out of this device"
              className="p-1 rounded transition-colors"
              style={{ color: 'var(--text-muted)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--error)'
                e.currentTarget.style.backgroundColor = 'var(--error-subtle)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--text-muted)'
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
              aria-label="Sign out"
            >
              <LogOut size={13} />
            </button>
          </div>
        </div>
      </aside>
    </>
  )
}
