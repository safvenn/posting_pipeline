import React, { useState } from 'react'
import { Menu, Terminal } from 'lucide-react'
import Sidebar from './Sidebar'

export default function Layout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <div className="main-layout min-h-screen bg-surface-base text-on-surface flex">
      {/* Mobile Top Header */}
      <div className="mobile-header md:hidden w-full flex items-center justify-between px-4 py-3 bg-surface-1 border-b border-border-subtle sticky top-0 z-30">
        <div className="flex items-center gap-2.5">
          <div className="relative w-7 h-7 rounded-lg bg-surface-2 border border-border-strong flex items-center justify-center">
            <Terminal size={15} className="text-primary" />
            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-status-success ring-1 ring-[#12161F] animate-pulse" />
          </div>
          <span className="text-sm font-bold text-on-surface tracking-tight">
            YT Pipeline
          </span>
          <span className="text-[10px] font-mono bg-surface-3 px-1.5 py-0.5 rounded text-primary border border-border-subtle">
            v2.4
          </span>
        </div>

        <button
          onClick={() => setSidebarOpen(o => !o)}
          className="p-1.5 rounded-lg bg-surface-2 border border-border-subtle text-on-surface-variant hover:text-on-surface"
          aria-label="Toggle navigation menu"
        >
          <Menu size={18} />
        </button>
      </div>

      {/* Persistent Sidebar */}
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main Content Area */}
      <div className="main-content-wrapper flex-1 flex flex-col min-w-0 bg-surface-base md:ml-64">
        {children}
      </div>
    </div>
  )
}
