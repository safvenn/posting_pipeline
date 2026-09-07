import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Eye, EyeOff, LogIn, Zap, Lock } from 'lucide-react'

export default function Login() {
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()

  const [form, setForm] = useState({ username: '', password: '' })
  const [showPwd, setShowPwd] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Already logged in → go to dashboard
  useEffect(() => {
    if (isAuthenticated) navigate('/', { replace: true })
  }, [isAuthenticated, navigate])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.username.trim() || !form.password) return
    setError('')
    setLoading(true)
    try {
      await login(form.username.trim(), form.password)
      navigate('/', { replace: true })
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Login failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>
      {/* Animated background blobs */}
      <div style={styles.blob1} />
      <div style={styles.blob2} />
      <div style={styles.blob3} />

      <div style={styles.card}>
        {/* Logo / Brand */}
        <div style={styles.brand}>
          <div style={styles.logoWrap}>
            <Zap size={22} color="#2F81F7" strokeWidth={2.5} />
          </div>
          <div>
            <div style={styles.brandName}>Pipeline</div>
            <div style={styles.brandSub}>YouTube Auto-Publisher</div>
          </div>
        </div>

        <h1 style={styles.heading}>Welcome back</h1>
        <p style={styles.subheading}>Sign in to manage your channels and schedule</p>

        <form onSubmit={handleSubmit} style={styles.form}>
          {/* Username */}
          <div style={styles.fieldWrap}>
            <label htmlFor="login-username" style={styles.label}>Username</label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              autoFocus
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              placeholder="adminn"
              style={styles.input}
              disabled={loading}
            />
          </div>

          {/* Password */}
          <div style={styles.fieldWrap}>
            <label htmlFor="login-password" style={styles.label}>Password</label>
            <div style={styles.pwdWrap}>
              <input
                id="login-password"
                type={showPwd ? 'text' : 'password'}
                autoComplete="current-password"
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                placeholder="••••••••"
                style={{ ...styles.input, paddingRight: 44 }}
                disabled={loading}
              />
              <button
                type="button"
                onClick={() => setShowPwd((v) => !v)}
                style={styles.eyeBtn}
                tabIndex={-1}
                aria-label={showPwd ? 'Hide password' : 'Show password'}
              >
                {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div style={styles.errorBox} role="alert">
              <Lock size={14} style={{ flexShrink: 0 }} />
              <span>{error}</span>
            </div>
          )}

          {/* Submit */}
          <button
            id="login-submit"
            type="submit"
            disabled={loading || !form.username.trim() || !form.password}
            style={{
              ...styles.submitBtn,
              opacity: loading || !form.username.trim() || !form.password ? 0.6 : 1,
              cursor: loading || !form.username.trim() || !form.password ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? (
              <>
                <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2, borderColor: 'rgba(255,255,255,0.3)', borderTopColor: '#fff' }} />
                <span>Signing in…</span>
              </>
            ) : (
              <>
                <LogIn size={16} />
                <span>Sign In</span>
              </>
            )}
          </button>
        </form>

        <p style={styles.hint}>
          Default password: <code style={styles.code}>admin@2026</code>
        </p>
      </div>
    </div>
  )
}

/* ---- Styles ---- */
const styles = {
  page: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'var(--bg-app)',
    position: 'relative',
    overflow: 'hidden',
    padding: '24px 16px',
  },
  blob1: {
    position: 'absolute',
    top: '-20%',
    left: '-10%',
    width: 600,
    height: 600,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(47,129,247,0.10) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  blob2: {
    position: 'absolute',
    bottom: '-15%',
    right: '-10%',
    width: 500,
    height: 500,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(63,185,80,0.07) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  blob3: {
    position: 'absolute',
    top: '40%',
    left: '60%',
    width: 300,
    height: 300,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(88,166,255,0.06) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  card: {
    position: 'relative',
    zIndex: 1,
    width: '100%',
    maxWidth: 420,
    background: 'var(--bg-card)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 16,
    padding: '36px 32px',
    boxShadow: '0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px rgba(47,129,247,0.08)',
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 28,
  },
  logoWrap: {
    width: 42,
    height: 42,
    borderRadius: 10,
    background: 'var(--accent-subtle)',
    border: '1px solid var(--accent-border)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  brandName: {
    fontSize: 16,
    fontWeight: 700,
    color: 'var(--text-primary)',
    letterSpacing: '-0.02em',
  },
  brandSub: {
    fontSize: 11,
    color: 'var(--text-muted)',
    marginTop: 1,
  },
  heading: {
    fontSize: 22,
    fontWeight: 700,
    color: 'var(--text-primary)',
    letterSpacing: '-0.03em',
    marginBottom: 6,
  },
  subheading: {
    fontSize: 13,
    color: 'var(--text-muted)',
    marginBottom: 28,
    lineHeight: 1.5,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 18,
  },
  fieldWrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  label: {
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--text-secondary)',
    letterSpacing: '0.02em',
  },
  input: {
    width: '100%',
    padding: '10px 14px',
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border-medium)',
    borderRadius: 8,
    color: 'var(--text-primary)',
    fontSize: 14,
    outline: 'none',
    transition: 'border-color 150ms, box-shadow 150ms',
    fontFamily: 'inherit',
  },
  pwdWrap: {
    position: 'relative',
  },
  eyeBtn: {
    position: 'absolute',
    right: 12,
    top: '50%',
    transform: 'translateY(-50%)',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-muted)',
    display: 'flex',
    alignItems: 'center',
    padding: 4,
  },
  errorBox: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 14px',
    background: 'var(--error-subtle)',
    border: '1px solid var(--error-border)',
    borderRadius: 8,
    color: 'var(--error)',
    fontSize: 13,
    lineHeight: 1.4,
  },
  submitBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    padding: '11px 20px',
    background: 'var(--accent-primary)',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    fontSize: 14,
    fontWeight: 600,
    fontFamily: 'inherit',
    cursor: 'pointer',
    transition: 'background 150ms, transform 100ms',
    marginTop: 4,
    width: '100%',
  },
  hint: {
    marginTop: 20,
    fontSize: 11.5,
    color: 'var(--text-subtle)',
    textAlign: 'center',
    lineHeight: 1.6,
  },
  code: {
    background: 'var(--bg-elevated)',
    padding: '1px 5px',
    borderRadius: 4,
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    color: 'var(--accent-hover)',
  },
}
