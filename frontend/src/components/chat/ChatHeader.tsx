import React, { useState } from 'react'
import { useChat } from '@/context/ChatContext'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Users, MoreVertical, Trash2, UserX, ShieldCheck } from 'lucide-react'
import { E2EEVerificationModal } from '../modals/E2EEVerificationModal'
import { GroupDetailModal } from '../modals/GroupDetailModal'
import { friendApi } from '@/api/client'

export const ChatHeader: React.FC = () => {
  const { activeConversation, refreshFriends, refreshConversations, setActiveConversation } = useChat()
  const [showGroupModal, setShowGroupModal] = useState(false)
  const [showE2eeModal, setShowE2eeModal] = useState(false)
  const [showMenu, setShowMenu] = useState(false)

  if (!activeConversation) return null

  const isGroup = activeConversation.type === 'group'

  const handleDeleteFriend = async () => {
    if (!window.confirm(`确定要解除与「${activeConversation.name}」的好友关系吗？`)) return
    try {
      await friendApi.deleteFriend(activeConversation.target_id)
      await refreshFriends()
      await refreshConversations()
      setActiveConversation(null)
    } catch (err) {
      alert('解除好友关系失败')
    }
  }

  return (
    <div className="h-16 px-6 bg-white border-b border-slate-100 flex items-center justify-between z-10">
      {/* Target Info */}
      <div className="flex items-center gap-3">
        <Avatar className="w-10 h-10 ring-2 ring-slate-50" isOnline={!isGroup ? activeConversation.is_online : undefined}>
          <AvatarImage src={activeConversation.avatar} />
          <AvatarFallback className={`font-semibold ${isGroup ? 'bg-indigo-100 text-indigo-700' : 'bg-blue-100 text-blue-700'}`}>
            {activeConversation.name.slice(0, 1)}
          </AvatarFallback>
        </Avatar>

        <div>
          <div className="font-bold text-sm text-slate-900 flex items-center gap-2">
            {activeConversation.name}
            {isGroup && (
              <span className="text-[11px] font-normal px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
                群聊
              </span>
            )}
          </div>
          <div className="text-xs text-slate-400 flex items-center gap-1.5">
            {isGroup ? (
              <span>{activeConversation.description || '点击右侧群图标查看成员'}</span>
            ) : (
              <span className="flex items-center gap-1">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    activeConversation.is_online ? 'bg-emerald-500' : 'bg-slate-300'
                  }`}
                />
                {activeConversation.is_online ? '在线' : '离线'}
                {activeConversation.bio && ` · ${activeConversation.bio}`}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Header Actions */}
      <div className="flex items-center gap-2 relative">
        <button
          onClick={() => setShowE2eeModal(true)}
          className="hidden sm:flex items-center gap-1 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200/60 text-emerald-700 text-xs font-medium hover:bg-emerald-100 transition shadow-2xs select-none"
          title="点击查看端到端加密安全码与认证参数"
        >
          <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
          <span>E2EE 已保护</span>
        </button>
        {isGroup ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setShowGroupModal(true)}
            className="text-slate-500 hover:text-indigo-600 rounded-xl"
            title="群成员与设置"
          >
            <Users className="w-5 h-5" />
          </Button>
        ) : (
          <div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowMenu(!showMenu)}
              className="text-slate-500 hover:text-slate-800 rounded-xl"
            >
              <MoreVertical className="w-5 h-5" />
            </Button>
            {showMenu && (
              <div className="absolute right-0 top-12 bg-white rounded-xl shadow-lg border border-slate-100 py-1 w-36 z-20 animate-in fade-in">
                <button
                  onClick={() => {
                    setShowMenu(false)
                    handleDeleteFriend()
                  }}
                  className="w-full px-3 py-2 text-left text-xs text-red-600 hover:bg-red-50 flex items-center gap-2 font-medium"
                >
                  <UserX className="w-4 h-4" /> 删除好友
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Group Detail Modal */}
      {isGroup && (
        <GroupDetailModal
          groupId={activeConversation.target_id}
          open={showGroupModal}
          onOpenChange={setShowGroupModal}
        />
      )}

      {/* E2EE Security Modal */}
      <E2EEVerificationModal
        open={showE2eeModal}
        onOpenChange={setShowE2eeModal}
        targetUserId={activeConversation.target_id}
        targetName={activeConversation.name}
        isGroup={isGroup}
      />
    </div>
  )
}
