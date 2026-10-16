import React, { useState } from 'react'
import { useAuth } from '@/context/AuthContext'
import { useChat } from '@/context/ChatContext'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { MessageSquare, Users, Compass, LogOut } from 'lucide-react'
import { ProfileModal } from '../modals/ProfileModal'

interface SidebarRailProps {
  currentTab: 'chats' | 'contacts' | 'groups'
  onTabChange: (tab: 'chats' | 'contacts' | 'groups') => void
}

export const SidebarRail: React.FC<SidebarRailProps> = ({ currentTab, onTabChange }) => {
  const { user, logout } = useAuth()
  const { conversations, friendRequests } = useChat()
  const [showProfileModal, setShowProfileModal] = useState(false)

  const totalUnread = conversations.reduce((acc, c) => acc + (c.unread_count || 0), 0)
  const pendingRequestsCount = friendRequests.received?.length || 0

  return (
    <div className="w-16 h-full bg-slate-900 flex flex-col items-center justify-between py-5 select-none shrink-0 z-20">
      {/* Top Logo & App brand */}
      <div className="flex flex-col items-center gap-6">
        <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white shadow-lg shadow-blue-500/30">
          <MessageSquare className="w-5 h-5" />
        </div>

        {/* Tab Buttons */}
        <div className="flex flex-col items-center gap-3">
          {/* Chats Tab */}
          <button
            type="button"
            onClick={() => onTabChange('chats')}
            className={`relative p-3 rounded-2xl transition-all ${
              currentTab === 'chats'
                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/40'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
            title="会话消息"
          >
            <MessageSquare className="w-5 h-5" />
            {totalUnread > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full ring-2 ring-slate-900 animate-pulse">
                {totalUnread > 99 ? '99+' : totalUnread}
              </span>
            )}
          </button>

          {/* Contacts / Friends Tab */}
          <button
            type="button"
            onClick={() => onTabChange('contacts')}
            className={`relative p-3 rounded-2xl transition-all ${
              currentTab === 'contacts'
                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/40'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
            title="好友通讯录"
          >
            <Users className="w-5 h-5" />
            {pendingRequestsCount > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full ring-2 ring-slate-900">
                {pendingRequestsCount}
              </span>
            )}
          </button>

          {/* Groups Tab */}
          <button
            type="button"
            onClick={() => onTabChange('groups')}
            className={`relative p-3 rounded-2xl transition-all ${
              currentTab === 'groups'
                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/40'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`}
            title="群组大厅"
          >
            <Compass className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* Bottom User Profile & Logout */}
      <div className="flex flex-col items-center gap-4">
        {/* User Avatar Click to Edit Profile */}
        <div
          className="cursor-pointer group relative"
          onClick={() => setShowProfileModal(true)}
          title="点击编辑个人资料"
        >
          <Avatar className="w-10 h-10 ring-2 ring-slate-700 hover:ring-blue-500 transition" isOnline={true}>
            <AvatarImage src={user?.avatar} />
            <AvatarFallback className="bg-blue-600 text-white font-bold text-xs">
              {user?.nickname.slice(0, 1)}
            </AvatarFallback>
          </Avatar>
        </div>

        {/* Logout Button */}
        <button
          type="button"
          onClick={logout}
          className="p-2.5 rounded-xl text-slate-400 hover:text-red-400 hover:bg-slate-800 transition"
          title="退出登录"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>

      {/* Profile Modal */}
      <ProfileModal open={showProfileModal} onOpenChange={setShowProfileModal} />
    </div>
  )
}
