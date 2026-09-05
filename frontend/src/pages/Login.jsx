import React, { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Terminal, Lock, User, Eye, EyeOff, ShieldCheck, AlertCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { formatErrorMessage } from '../api/client'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from?.pathname || '/'

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Please enter both username and password.')
      return
    }

    setError('')
    setSubmitting(true)

    try {
      await login(username.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      if (err.response?.status === 401) {
        setError('Invalid credentials. Access restricted to authorized operators.')
      } else {
        setError(formatErrorMessage(err))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: 'var(--bg-base)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px 16px',
        position: 'relative',
        overflow: 'hidden',
        fontFamily: 'var(--font-sans)',
      }}
    >
      {/* Background subtle radial glow */}
      <div
        style={{
          position: 'absolute',
          top: '20%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 500,
          height: 350,
          background: 'radial-gradient(circle, rgba(99, 102, 241, 0.08) 0%, rgba(99, 102, 241, 0) 70%)',
          pointerEvents: 'none',
        }}
      />

      <div
        className="w-full max-w-[420px] rounded-xl border border-border-subtle p-8 shadow-2xl relative z-10"
        style={{
          backgroundColor: 'var(--bg-surface)',
          boxShadow: '0 20px 40px -15px rgba(0, 0, 0, 0.5)',
        }}
      >
        {/* Header / Logo */}
        <div className="flex flex-col items-center text-center mb-8">
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center mb-3.5 relative"
            style={{
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-medium)',
            }}
          >
            <Terminal size={22} style={{ color: 'var(--accent-primary)' }} />
            <span
              className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: 'var(--success)' }}
            />
          </div>
          <h1 className="text-xl font-bold tracking-tight" style={{ color: 'var(--text-primary)' }}>
            Pipeline Access
          </h1>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            Sign in once to authenticate this device
          </p>
        </div>

        {/* Error Alert */}
        {error && (
          <div
            className="mb-5 p-3 rounded-lg flex items-start gap-2.5 text-xs"
            style={{
              backgroundColor: 'var(--error-subtle)',
              border: '1px solid var(--error-border)',
              color: 'var(--error)',
            }}
          >
            <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
            <div className="leading-relaxed">{error}</div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              Username
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none" style={{ color: 'var(--text-muted)' }}>
                <User size={15} />
              </span>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                placeholder="Enter username"
                className="input pl-9 w-full text-sm"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold mb-1.5" style={{ color: 'var(--text-secondary)' }}>
              Password
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none" style={{ color: 'var(--text-muted)' }}>
                <Lock size={15} />
              </span>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="Enter password"
                className="input pl-9 pr-9 w-full text-sm font-mono"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-outline hover:text-on-surface"
                style={{ color: 'var(--text-muted)' }}
                aria-label="Toggle password visibility"
              >
                {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>

          {/* Device Persistence Badge */}
          <div
            className="p-2.5 rounded-lg flex items-center gap-2 text-[11px]"
            style={{
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
              color: 'var(--text-muted)',
            }}
          >
            <ShieldCheck size={14} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
            <span>Device credentials will be persisted for 30 days</span>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="btn btn-primary w-full justify-center py-2.5 mt-2 font-medium"
          >
            {submitting ? (
              <div className="flex items-center gap-2">
                <span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
                <span>Authenticating...</span>
              </div>
            ) : (
              <span>Sign In to Dashboard</span>
            )}
          </button>
        </form>
      </div>
    </div>
  )
}
