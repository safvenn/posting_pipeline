import axios from 'axios'

const rawApiUrl = import.meta.env.VITE_API_URL
const apiBase = rawApiUrl
  ? (rawApiUrl.endsWith('/api') ? rawApiUrl : `${rawApiUrl.replace(/\/+$/, '')}/api`)
  : '/api'

const client = axios.create({
  baseURL: apiBase,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

export { apiBase }
export default client

