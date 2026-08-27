import axios from 'axios'

const rawApiUrl = import.meta.env.VITE_API_URL
const apiBase = rawApiUrl
  ? (rawApiUrl.endsWith('/api') ? rawApiUrl : `${rawApiUrl.replace(/\/+$/, '')}/api`)
  : '/api'

const client = axios.create({
  baseURL: apiBase,
  timeout: 180000,
})

// Inject API key as Bearer token on every request (if configured)
client.interceptors.request.use(
  (config) => {
    const key = import.meta.env.VITE_API_KEY || (typeof window !== 'undefined' && window.localStorage?.getItem('pipeline_api_key'))
    if (key) {
      config.headers.Authorization = `Bearer ${key}`
    }
    return config
  },
  (error) => Promise.reject(error)
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


