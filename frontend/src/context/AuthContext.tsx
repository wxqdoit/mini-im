import React, { createContext, useContext, useState, useEffect } from 'react'
import { User } from '../types'
import { authApi, userApi } from '../api/client'

interface AuthContextType {
  user: User | null
  token: string | null
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, nickname?: string, avatar?: string, bio?: string) => Promise<void>
  logout: () => Promise<void>
  updateProfile: (data: { nickname?: string; bio?: string; avatar?: string; status?: string }) => Promise<void>
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('mini_im_token'))
  const [isLoading, setIsLoading] = useState<boolean>(true)

  const refreshMe = async () => {
    try {
      const res = await authApi.getMe()
      setUser(res.data.user)
    } catch (err) {
      console.error('Failed to load current user', err)
      logout()
    }
  }

  useEffect(() => {
    if (token) {
      refreshMe().finally(() => setIsLoading(false))
    } else {
      setIsLoading(false)
    }
  }, [token])

  const login = async (username: string, password: string) => {
    const res = await authApi.login({ username, password })
    const { token: newToken, user: newUser } = res.data
    localStorage.setItem('mini_im_token', newToken)
    setToken(newToken)
    setUser(newUser)
  }

  const register = async (username: string, password: string, nickname?: string, avatar?: string, bio?: string) => {
    const res = await authApi.register({ username, password, nickname, avatar, bio })
    const { token: newToken, user: newUser } = res.data
    localStorage.setItem('mini_im_token', newToken)
    setToken(newToken)
    setUser(newUser)
  }

  const logout = async () => {
    const curToken = token || localStorage.getItem('mini_im_token')
    localStorage.removeItem('mini_im_token')
    setToken(null)
    setUser(null)
    if (curToken) {
      try {
        await authApi.logout(curToken)
      } catch (e) {
        // Ignore network errors on logout
      }
    }
  }

  const updateProfile = async (data: { nickname?: string; bio?: string; avatar?: string; status?: string }) => {
    const res = await userApi.updateProfile(data)
    setUser(res.data.user)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        register,
        logout,
        updateProfile,
        refreshMe,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
