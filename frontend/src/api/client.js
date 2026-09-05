import axios from 'axios'

const rawApiUrl = import.meta.env.VITE_API_URL
const apiBase = rawApiUrl
  ? (rawApiUrl.endsWith('/api') ? rawApiUrl : `${rawApiUrl.replace(/\/+$/, '')}/api`)
  : '/api'

const client = axios.create({
  baseURL: apiBase,
  timeout: 180000,
})

let currentAccessToken = typeof window !== 'undefined' ? localStorage.getItem('pipeline_access_token') : null

export function setTokens(accessToken, refreshToken) {
  currentAccessToken = accessToken
  if (typeof window !== 'undefined') {
    if (accessToken) {
      localStorage.setItem('pipeline_access_token', accessToken)
    } else {
      localStorage.removeItem('pipeline_access_token')
    }
    if (refreshToken) {
      localStorage.setItem('pipeline_refresh_token', refreshToken)
    } else {
      localStorage.removeItem('pipeline_refresh_token')
    }
  }
}

export function getRefreshToken() {
  return typeof window !== 'undefined' ? localStorage.getItem('pipeline_refresh_token') : null
}

export function clearTokens() {
  currentAccessToken = null
  if (typeof window !== 'undefined') {
    localStorage.removeItem('pipeline_access_token')
    localStorage.removeItem('pipeline_refresh_token')
  }
}

// Request interceptor: attach Authorization header
client.interceptors.request.use(
  (config) => {
    // 1. If we have a JWT access token, use it
    if (currentAccessToken) {
      config.headers.Authorization = `Bearer ${currentAccessToken}`
    } else {
      // 2. Fallback to API key if present
      const key = import.meta.env.VITE_API_KEY || (typeof window !== 'undefined' && window.localStorage?.getItem('pipeline_api_key'))
      if (key) {
        config.headers.Authorization = `Bearer ${key}`
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor: handle 401 and auto-refresh token
let isRefreshing = false
let refreshSubscribers = []

function subscribeTokenRefresh(cb) {
  refreshSubscribers.push(cb)
}

function onRefreshed(token) {
  refreshSubscribers.forEach((cb) => cb(token))
  refreshSubscribers = []
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    if (!originalRequest) return Promise.reject(error)

    // Skip refresh for auth endpoints
    if (
      originalRequest.url?.includes('/auth/login') ||
      originalRequest.url?.includes('/auth/refresh')
    ) {
      return Promise.reject(error)
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        clearTokens()
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('pipeline-auth-expired'))
        }
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh((newToken) => {
            if (newToken) {
              originalRequest.headers.Authorization = `Bearer ${newToken}`
              resolve(client(originalRequest))
            } else {
              reject(error)
            }
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const res = await axios.post(`${apiBase}/auth/refresh`, {
          refresh_token: refreshToken,
        })
        const newAccessToken = res.data.access_token
        setTokens(newAccessToken, refreshToken)
        isRefreshing = false
        onRefreshed(newAccessToken)

        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`
        return client(originalRequest)
      } catch (refreshErr) {
        isRefreshing = false
        onRefreshed(null)
        clearTokens()
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('pipeline-auth-expired'))
        }
        return Promise.reject(refreshErr)
      }
    }

    return Promise.reject(error)
  }
)

export function formatErrorMessage(err) {
  if (!err) return 'An unexpected error occurred.'
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(d => (d && typeof d === 'object' && d.msg) ? `${d.loc ? d.loc.slice(-1)[0] + ': ' : ''}${d.msg}` : String(d)).join(', ')
  }
  if (detail && typeof detail === 'object') {
    return JSON.stringify(detail)
  }
  return err.response?.data?.message || err.message || String(err)
}

export { apiBase }
export default client
