import React from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ChatProvider } from './context/ChatContext'
import { AuthPage } from './components/auth/AuthPage'
import { MainLayout } from './components/layout/MainLayout'
import { Loader2 } from 'lucide-react'

const AppContent: React.FC = () => {
  const { user, token, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-slate-50 gap-3">
        <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
        <span className="text-xs text-slate-400 font-medium">正在加载 Mini IM...</span>
      </div>
    )
  }

  if (!token || !user) {
    return <AuthPage />
  }

  return (
    <ChatProvider>
      <MainLayout />
    </ChatProvider>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
