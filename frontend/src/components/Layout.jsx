import React, { useState } from 'react'
import { Menu, Terminal } from 'lucide-react'
import Sidebar from './Sidebar'

export default function Layout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="main-layout">
      {/* Mobile Top Header — only visible below md (900px) via CSS .mobile-header */}
      <div className="mobile-header">
        <div className="flex items-center gap-2.5">
          <div className="relative w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-medium)' }}>
            <Terminal size={13} style={{ color: 'var(--accent-primary)' }} />
            <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full"
              style={{ backgroundColor: 'var(--success)' }} />
          </div>
          <span className="font-bold tracking-tight" style={{ fontSize: 14, color: 'var(--text-primary)' }}>
            YT Pipeline
          </span>
          <span className="font-mono rounded px-1 py-0.5"
            style={{ fontSize: 10, backgroundColor: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border-subtle)' }}>
            v2.4
          </span>
        </div>

        <button
          onClick={() => setSidebarOpen(o => !o)}
          className="p-1.5 rounded-lg"
          style={{ backgroundColor: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)', color: 'var(--text-secondary)' }}
          aria-label="Toggle navigation menu"
        >
          <Menu size={17} />
        </button>
      </div>

      {/* Sidebar */}
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main content — margin-left matches sidebar width via CSS */}
      <div className="main-content-wrapper">
        {children}
      </div>
    </div>
  )
}

