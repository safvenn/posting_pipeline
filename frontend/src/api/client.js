import axios from 'axios'

const rawApiUrl = import.meta.env.VITE_API_URL
const apiBase = rawApiUrl
  ? (rawApiUrl.endsWith('/api') ? rawApiUrl : `${rawApiUrl.replace(/\/+$/, '')}/api`)
  : '/api'

const client = axios.create({
  baseURL: apiBase,
  timeout: 180000,
})

// ---------------------------------------------------------------------------
// Request interceptor — inject the best available auth token
// Priority: JWT access_token > static VITE_API_KEY > localStorage pipeline_api_key
// ---------------------------------------------------------------------------
client.interceptors.request.use(
  (config) => {
    // Prefer JWT token from localStorage if available
    try {
      const raw = localStorage.getItem('pipeline_jwt')
      const jwt = raw ? JSON.parse(raw) : null
      if (jwt?.access_token) {
        config.headers.Authorization = `Bearer ${jwt.access_token}`
        return config
      }
    } catch {}

    // Fall back to static API key
    const key =
      import.meta.env.VITE_API_KEY ||
      (typeof window !== 'undefined' && window.localStorage?.getItem('pipeline_api_key'))
    if (key) {
      config.headers.Authorization = `Bearer ${key}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// ---------------------------------------------------------------------------
// Response interceptor — auto-refresh JWT on 401
// ---------------------------------------------------------------------------
let _refreshing = false
let _pendingQueue = []

function processQueue(error, token = null) {
  _pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token)
  })
  _pendingQueue = []
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    // Only retry 401 once, and only if we have a refresh token
    if (error.response?.status === 401 && !original._retried) {
      original._retried = true

      // Skip retry for auth endpoints themselves to avoid infinite loops
      if (original.url?.includes('/auth/')) {
        return Promise.reject(error)
      }

      try {
        const raw = localStorage.getItem('pipeline_jwt')
        const stored = raw ? JSON.parse(raw) : null
        if (!stored?.refresh_token) return Promise.reject(error)

        if (_refreshing) {
          // Queue this request until refresh completes
          return new Promise((resolve, reject) => {
            _pendingQueue.push({ resolve, reject })
          }).then((token) => {
            original.headers.Authorization = `Bearer ${token}`
            return client(original)
          })
        }

        _refreshing = true
        const resp = await axios.post(`${apiBase}/auth/refresh`, {
          refresh_token: stored.refresh_token,
        })
        const newTokens = resp.data
        localStorage.setItem('pipeline_jwt', JSON.stringify(newTokens))
        processQueue(null, newTokens.access_token)
        _refreshing = false

        original.headers.Authorization = `Bearer ${newTokens.access_token}`
        return client(original)
      } catch (refreshErr) {
        _refreshing = false
        processQueue(refreshErr, null)
        // Clear tokens — session expired
        localStorage.removeItem('pipeline_jwt')
        // Redirect to login
        if (typeof window !== 'undefined') {
          window.location.href = '/login'
        }
        return Promise.reject(refreshErr)
      }
    }
    return Promise.reject(error)
  },
)

export function formatErrorMessage(err) {
  if (!err) return 'An unexpected error occurred.'
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) =>
        d && typeof d === 'object' && d.msg
          ? `${d.loc ? d.loc.slice(-1)[0] + ': ' : ''}${d.msg}`
          : String(d),
      )
      .join(', ')
  }
  if (detail && typeof detail === 'object') {
    return JSON.stringify(detail)
  }
  return err.response?.data?.message || err.message || String(err)
}

export { apiBase }
export default client
