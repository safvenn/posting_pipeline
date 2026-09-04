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
  X,
} from 'lucide-react'
import { usePostsQuery } from '../hooks/usePosts'
import { useChannelsQuery } from '../hooks/useChannels'

export default function Sidebar({ isOpen, onClose }) {
  const [time, setTime] = useState('')
  const navigate = useNavigate()

  // Cached queries — zero overhead since Dashboard already subscribes
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
        second: '2-digit',
        hour12: true,
      }))
    }
    updateClock()
    const timer = setInterval(updateClock, 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <>
      {isOpen && (
        <div
          onClick={onClose}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(5, 7, 10, 0.75)',
            backdropFilter: 'blur(4px)',
            zIndex: 35,
          }}
        />
      )}

      <aside className={`sidebar ${isOpen ? 'open' : ''} fixed top-0 left-0 h-screen w-64 z-40 bg-surface-1 border-r border-border-subtle flex flex-col justify-between p-4 select-none`}>
        {/* Top Header & Branding */}
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between pb-1">
            <div className="flex items-center gap-3">
              <div className="relative w-9 h-9 rounded-lg bg-surface-2 border border-border-strong flex items-center justify-center shadow-inner">
                <Terminal size={18} className="text-primary" />
                <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-status-success ring-2 ring-[#12161F] animate-pulse" />
              </div>
              <div className="overflow-hidden">
                <div className="flex items-center gap-1.5">
                  <h1 className="text-sm font-bold text-on-surface tracking-tight">YT Pipeline</h1>
                  <span className="text-[10px] font-mono bg-surface-3 px-1.5 py-0.5 rounded text-primary border border-border-subtle">v2.4</span>
                </div>
                <p className="text-[11px] font-mono text-outline truncate mt-0.5">Queue Active • 1 Post/Run</p>
              </div>
            </div>

            {onClose && (
              <button
                onClick={onClose}
                className="md:hidden p-1 rounded-lg text-outline hover:text-on-surface hover:bg-surface-2 transition-colors"
                aria-label="Close sidebar"
              >
                <X size={18} />
              </button>
            )}
          </div>

          {/* Quick CTA Button inside Nav */}
          <button
            className="w-full flex items-center justify-center gap-2 bg-[#3B82F6] hover:bg-[#2563EB] text-white font-semibold text-xs py-2.5 px-3 rounded-lg shadow-sm active:scale-[0.98] transition-all"
            onClick={() => {
              navigate('/upload')
              if (onClose) onClose()
            }}
          >
            <Upload size={15} />
            <span>Upload Video</span>
          </button>

          {/* Category: PIPELINE */}
          <div className="pt-2">
            <div className="px-3 pb-2 text-label-caps text-outline uppercase tracking-wider text-[11px]">
              Pipeline
            </div>
            <nav className="flex flex-col gap-1">
              {/* Dashboard */}
              <NavLink
                to="/"
                end
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 text-xs rounded-lg transition-colors ${
                    isActive
                      ? 'bg-surface-2 text-primary border-l-2 border-[#3B82F6] font-semibold rounded-l-none shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-2 font-medium'
                  }`
                }
              >
                <LayoutDashboard size={16} />
                <span>Dashboard</span>
              </NavLink>

              {/* Upload Video */}
              <NavLink
                to="/upload"
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 text-xs rounded-lg transition-colors ${
                    isActive
                      ? 'bg-surface-2 text-primary border-l-2 border-[#3B82F6] font-semibold rounded-l-none shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-2 font-medium'
                  }`
                }
              >
                <Upload size={16} />
                <span>Upload Video</span>
              </NavLink>

              {/* Schedule Matrix */}
              <NavLink
                to="/schedule"
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center justify-between px-3 py-2 text-xs rounded-lg transition-colors ${
                    isActive
                      ? 'bg-surface-2 text-primary border-l-2 border-[#3B82F6] font-semibold rounded-l-none shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-2 font-medium'
                  }`
                }
              >
                <div className="flex items-center gap-3">
                  <Calendar size={16} />
                  <span>Schedule Matrix</span>
                </div>
                {scheduledCount > 0 && (
                  <span className="text-[10px] font-mono bg-surface-3 text-on-surface-variant px-1.5 py-0.5 rounded border border-border-subtle">
                    {scheduledCount}
                  </span>
                )}
              </NavLink>
            </nav>
          </div>

          {/* Category: AUTOMATION & CONFIG */}
          <div className="pt-2">
            <div className="px-3 pb-2 text-label-caps text-outline uppercase tracking-wider text-[11px]">
              Automation &amp; Config
            </div>
            <nav className="flex flex-col gap-1">
              {/* ASMR Studio */}
              <NavLink
                to="/asmr"
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 text-xs rounded-lg transition-colors ${
                    isActive
                      ? 'bg-surface-2 text-primary border-l-2 border-[#3B82F6] font-semibold rounded-l-none shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-2 font-medium'
                  }`
                }
              >
                <Sparkles size={16} />
                <span>ASMR Studio</span>
              </NavLink>

              {/* Channels */}
              <NavLink
                to="/channels"
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center justify-between px-3 py-2 text-xs rounded-lg transition-colors ${
                    isActive
                      ? 'bg-surface-2 text-primary border-l-2 border-[#3B82F6] font-semibold rounded-l-none shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-2 font-medium'
                  }`
                }
              >
                <div className="flex items-center gap-3">
                  <Tv2 size={16} />
                  <span>Channels</span>
                </div>
                <span className="text-[10px] font-mono text-outline">
                  {channels.length} Live
                </span>
              </NavLink>

              {/* Failed Jobs */}
              <NavLink
                to="/failed"
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center justify-between px-3 py-2 text-xs rounded-lg transition-colors group ${
                    isActive
                      ? 'bg-surface-2 text-status-danger border-l-2 border-[#F43F5E] font-semibold rounded-l-none shadow-sm'
                      : 'text-on-surface-variant hover:text-status-danger hover:bg-surface-2 font-medium'
                  }`
                }
              >
                <div className="flex items-center gap-3">
                  <AlertTriangle size={16} className="text-status-danger" />
                  <span>Failed Jobs</span>
                </div>
                {failedCount > 0 && (
                  <span className="text-[10px] font-mono bg-status-danger/15 text-status-danger border border-status-danger/30 px-1.5 py-0.5 rounded font-semibold">
                    {failedCount}
                  </span>
                )}
              </NavLink>
            </nav>
          </div>
        </div>

        {/* Sidebar Footer Telemetry */}
        <div className="border-t border-border-subtle pt-3 flex flex-col gap-2.5">
          {/* Live Clock */}
          <div className="flex items-center justify-between px-2 text-xs font-mono text-outline">
            <span className="flex items-center gap-1.5 font-medium">
              <span className="w-2 h-2 rounded-full bg-status-success animate-pulse" />
              IST TIME
            </span>
            <span className="text-on-surface font-semibold tabular-nums">
              {time || '04:00:00 PM'}
            </span>
          </div>

          {/* Engine Load Status */}
          <div className="bg-surface-2 p-2.5 rounded-lg border border-border-subtle space-y-1.5">
            <div className="flex items-center justify-between text-outline text-[10px] font-mono">
              <span>SYSTEM LOAD</span>
              <span className="text-status-success font-medium">99.8% UPTIME</span>
            </div>
            <div className="w-full bg-surface-base h-1 rounded-full overflow-hidden">
              <div className="bg-[#3B82F6] h-full w-[28%]" />
            </div>
            <div className="flex items-center justify-between text-[10px] font-mono text-outline">
              <span>CPU: 18%</span>
              <span>RAM: 2.1 / 8GB</span>
            </div>
          </div>

          {/* Auto-refresh footer item */}
          <div className="flex items-center justify-between px-2 py-0.5 text-xs font-mono text-outline">
            <div className="flex items-center gap-1.5">
              <RefreshCw size={13} className="text-primary animate-spin" style={{ animationDuration: '4s' }} />
              <span>Auto-Refresh</span>
            </div>
            <span className="text-primary font-medium">15s</span>
          </div>
        </div>
      </aside>
    </>
  )
}
