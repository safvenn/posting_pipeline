import React, { useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Upload,
  Calendar,
  Tv2,
  AlertTriangle,
  Zap,
  Sparkles,
  Layers,
  Clock,
  Radio,
  X,
} from 'lucide-react'

const NAV_MAIN = [
  { to: '/',         icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/upload',   icon: Upload,          label: 'Upload Video' },
  { to: '/schedule', icon: Calendar,        label: 'Schedule Matrix' },
]

const NAV_AUTOMATION = [
  { to: '/asmr',     icon: Sparkles,        label: 'ASMR Studio' },
  { to: '/channels', icon: Tv2,             label: 'Channels' },
  { to: '/failed',   icon: AlertTriangle,   label: 'Failed Jobs' },
]

export default function Sidebar({ isOpen, onClose }) {
  const [time, setTime] = useState('')

  useEffect(() => {
    function updateClock() {
      const now = new Date()
      setTime(now.toLocaleTimeString('en-IN', {
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
            background: 'rgba(5, 7, 10, 0.7)',
            backdropFilter: 'blur(3px)',
            zIndex: 35,
          }}
        />
      )}

      <nav className={`sidebar ${isOpen ? 'open' : ''}`}>
        {/* Header / Brand Logo */}
        <div className="sidebar-logo">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              background: 'linear-gradient(135deg, #7C5CFF 0%, #4D5461 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 8px rgba(124, 92, 255, 0.35)',
            }}>
              <Zap size={17} color="#FFFFFF" />
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.02em', lineHeight: 1.2 }}>
                YT Pipeline
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 500 }}>
                Automation Engine
              </div>
            </div>
          </div>

          {onClose && (
            <button
              onClick={onClose}
              className="btn btn-ghost btn-sm btn-icon"
              style={{ display: 'none' }}
              aria-label="Close sidebar"
            >
              <X size={15} />
            </button>
          )}
        </div>

        {/* Navigation Sections */}
        <div className="sidebar-nav">
          <div className="sidebar-nav-section-title">Pipeline</div>
          {NAV_MAIN.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                `sidebar-nav-item${isActive ? ' active' : ''}`
              }
            >
              <Icon size={16} />
              <span>{label}</span>
            </NavLink>
          ))}

          <div className="sidebar-nav-section-title" style={{ marginTop: 12 }}>Automation & Config</div>
          {NAV_AUTOMATION.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className={({ isActive }) =>
                `sidebar-nav-item${isActive ? ' active' : ''}`
              }
            >
              <Icon size={16} />
              <span>{label}</span>
            </NavLink>
          ))}
        </div>

        {/* Status & Clock Footer */}
        <div className="sidebar-footer">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                backgroundColor: 'var(--success)',
                boxShadow: '0 0 8px var(--success)',
                display: 'inline-block',
              }} />
              <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600 }}>
                Queue Active
              </span>
            </div>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              1 Post / Run
            </span>
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 11,
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}>
            <Clock size={12} color="var(--text-muted)" />
            <span>IST: {time || '—'}</span>
          </div>
        </div>
      </nav>
    </>
  )
}
