import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import client, { apiBase, setTokens, getRefreshToken, clearTokens } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [isLoading, setIsLoading] = useState(true)

  const logout = useCallback(() => {
    try {
      client.post('/auth/logout').catch(() => {})
    } finally {
      clearTokens()
      setUser(null)
    }
  }, [])

  // Restore session from refresh token on load (persistent per-device login)
  useEffect(() => {
    let mounted = true

    async function initAuth() {
      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        if (mounted) setIsLoading(false)
        return
      }

      try {
        const res = await axios.post(`${apiBase}/auth/refresh`, {
          refresh_token: refreshToken,
        })
        const newAccessToken = res.data.access_token
        setTokens(newAccessToken, refreshToken)

        const meRes = await client.get('/auth/me')
        if (mounted) {
          setUser(meRes.data.username || 'adminn')
        }
      } catch (err) {
        console.warn('Persistent session restore failed:', err)
        clearTokens()
        if (mounted) setUser(null)
      } finally {
        if (mounted) setIsLoading(false)
      }
    }

    initAuth()

    const handleAuthExpired = () => {
      clearTokens()
      setUser(null)
    }
    window.addEventListener('pipeline-auth-expired', handleAuthExpired)

    return () => {
      mounted = false
      window.removeEventListener('pipeline-auth-expired', handleAuthExpired)
    }
  }, [])

  const login = async (username, password) => {
    const res = await client.post('/auth/login', { username, password })
    const { access_token, refresh_token } = res.data
    setTokens(access_token, refresh_token)
    setUser(username)
    return res.data
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
