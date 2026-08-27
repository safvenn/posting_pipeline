import React from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Home, ArrowLeft } from 'lucide-react'

export default function NotFound() {
  const navigate = useNavigate()

  return (
    <div style={{ maxWidth: 600, margin: '60px auto', textAlign: 'center' }}>
      <div
        style={{
          width: 64,
          height: 64,
          borderRadius: 16,
          backgroundColor: 'rgba(239, 68, 68, 0.12)',
          border: '1px solid rgba(239, 68, 68, 0.25)',
          color: 'var(--error)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 20px',
        }}
      >
        <AlertCircle size={32} />
      </div>

      <h1 className="page-title" style={{ justifyContent: 'center', fontSize: 24, marginBottom: 8 }}>
        404 — Page Not Found
      </h1>
      <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 28, lineHeight: 1.5 }}>
        The route you requested does not exist or has been moved. Use the navigation sidebar or return to the main dashboard.
      </p>

      <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
        <button
          className="btn btn-secondary"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft size={14} />
          <span>Go Back</span>
        </button>

        <button
          className="btn btn-primary"
          onClick={() => navigate('/')}
        >
          <Home size={14} />
          <span>Dashboard</span>
        </button>
      </div>
    </div>
  )
}
