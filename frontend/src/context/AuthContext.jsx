/**
 * AuthContext — JWT token management for the pipeline dashboard.
 *
 * Stores access_token + refresh_token in localStorage.
 * Automatically refreshes the access token when it expires (via axios interceptor).
 */
import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react'
import axios from 'axios'

const AuthContext = createContext(null)

const rawApiUrl = import.meta.env.VITE_API_URL
const apiBase = rawApiUrl
  ? (rawApiUrl.endsWith('/api') ? rawApiUrl : `${rawApiUrl.replace(/\/+$/, '')}/api`)
  : '/api'

const STORAGE_KEY = 'pipeline_jwt'

function loadTokens() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function saveTokens(tokens) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens))
  } catch {}
}

function clearTokens() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {}
}

export function AuthProvider({ children }) {
  const [tokens, setTokens] = useState(() => loadTokens())
  const refreshPromise = useRef(null)

  const isAuthenticated = Boolean(tokens?.access_token)

  const login = useCallback(async (username, password) => {
    const resp = await axios.post(`${apiBase}/auth/login`, { username, password })
    const data = resp.data
    setTokens(data)
    saveTokens(data)
    return data
  }, [])

  const logout = useCallback(() => {
    setTokens(null)
    clearTokens()
  }, [])

  const refreshAccessToken = useCallback(async () => {
    // Deduplicate concurrent refresh calls
    if (refreshPromise.current) return refreshPromise.current
    refreshPromise.current = (async () => {
      try {
        const stored = loadTokens()
        if (!stored?.refresh_token) throw new Error('No refresh token')
        const resp = await axios.post(`${apiBase}/auth/refresh`, {
          refresh_token: stored.refresh_token,
        })
        const data = resp.data
        setTokens(data)
        saveTokens(data)
        return data.access_token
      } catch {
        setTokens(null)
        clearTokens()
        throw new Error('Session expired. Please log in again.')
      } finally {
        refreshPromise.current = null
      }
    })()
    return refreshPromise.current
  }, [])

  const getAccessToken = useCallback(() => {
    return loadTokens()?.access_token || null
  }, [])

  return (
    <AuthContext.Provider value={{ isAuthenticated, tokens, login, logout, refreshAccessToken, getAccessToken }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
