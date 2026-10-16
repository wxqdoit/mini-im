import React, { useState } from 'react'
import { useChat } from '@/context/ChatContext'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { UserPlus, UserCheck, Search, MessageSquare, Users } from 'lucide-react'
import { AddFriendModal } from '../modals/AddFriendModal'
import { FriendRequestsModal } from '../modals/FriendRequestsModal'

export const ContactsView: React.FC = () => {
  const { friends, friendRequests, selectConversationByTarget } = useChat()
  const [query, setQuery] = useState('')
  const [showAddModal, setShowAddModal] = useState(false)
  const [showRequestsModal, setShowRequestsModal] = useState(false)

  const pendingCount = friendRequests.received?.length || 0

  const filtered = friends.filter(f =>
    f.nickname.toLowerCase().includes(query.toLowerCase()) ||
    f.username.toLowerCase().includes(query.toLowerCase())
  )

  const onlineFriends = filtered.filter(f => f.is_online)
  const offlineFriends = filtered.filter(f => !f.is_online)

  return (
    <div className="w-80 h-full bg-white border-r border-slate-100 flex flex-col shrink-0">
      {/* Header with action buttons */}
      <div className="p-4 border-b border-slate-100/80 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-900">通讯录好友</h2>
          <span className="text-xs text-slate-400 font-medium">共 {friends.length} 位好友</span>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Button
            size="sm"
            variant="default"
            className="text-xs h-8 gap-1 rounded-xl bg-blue-600 hover:bg-blue-700"
            onClick={() => setShowAddModal(true)}
          >
            <UserPlus className="w-3.5 h-3.5" /> 添加好友
          </Button>

          <Button
            size="sm"
            variant="outline"
            className="text-xs h-8 gap-1 rounded-xl relative"
            onClick={() => setShowRequestsModal(true)}
          >
            <UserCheck className="w-3.5 h-3.5" /> 好友申请
            {pendingCount > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full">
                {pendingCount}
              </span>
            )}
          </Button>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索好友昵称或用户名..."
            className="pl-9 h-9 bg-slate-50 border-slate-200/80 rounded-xl text-xs"
          />
        </div>
      </div>

      {/* Friends list */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-50">
        {filtered.length > 0 ? (
          <div>
            {/* Online section */}
            {onlineFriends.length > 0 && (
              <div className="px-4 py-2 bg-slate-50/60 text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                <span>在线好友</span>
                <span className="text-emerald-600 font-semibold">{onlineFriends.length}</span>
              </div>
            )}
            {onlineFriends.map(f => (
              <div
                key={f.id}
                onClick={() => selectConversationByTarget('direct', f.id)}
                className="p-3.5 flex items-center justify-between hover:bg-slate-50/80 cursor-pointer transition"
              >
                <div className="flex items-center gap-3">
                  <Avatar className="w-10 h-10" isOnline={true}>
                    <AvatarImage src={f.avatar} />
                    <AvatarFallback className="bg-blue-100 text-blue-700 font-bold">
                      {f.nickname.slice(0, 1)}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <div className="font-semibold text-sm text-slate-800">{f.nickname}</div>
                    <div className="text-xs text-slate-400 truncate max-w-[140px]">
                      {f.bio || '暂无个性签名'}
                    </div>
                  </div>
                </div>
                <Button size="icon" variant="ghost" className="h-8 w-8 text-slate-400 hover:text-blue-600">
                  <MessageSquare className="w-4 h-4" />
                </Button>
              </div>
            ))}

            {/* Offline section */}
            {offlineFriends.length > 0 && (
              <div className="px-4 py-2 bg-slate-50/60 text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                <span>离线好友</span>
                <span>{offlineFriends.length}</span>
              </div>
            )}
            {offlineFriends.map(f => (
              <div
                key={f.id}
                onClick={() => selectConversationByTarget('direct', f.id)}
                className="p-3.5 flex items-center justify-between hover:bg-slate-50/80 cursor-pointer transition"
              >
                <div className="flex items-center gap-3">
                  <Avatar className="w-10 h-10" isOnline={false}>
                    <AvatarImage src={f.avatar} />
                    <AvatarFallback className="bg-slate-100 text-slate-600 font-bold">
                      {f.nickname.slice(0, 1)}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <div className="font-semibold text-sm text-slate-800">{f.nickname}</div>
                    <div className="text-xs text-slate-400 truncate max-w-[140px]">
                      {f.bio || '暂无个性签名'}
                    </div>
                  </div>
                </div>
                <Button size="icon" variant="ghost" className="h-8 w-8 text-slate-400 hover:text-blue-600">
                  <MessageSquare className="w-4 h-4" />
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <div className="py-20 text-center text-xs text-slate-400 flex flex-col items-center justify-center gap-2">
            <Users className="w-8 h-8 text-slate-200" />
            <span>暂无好友，点击上方“添加好友”寻找朋友吧</span>
          </div>
        )}
      </div>

      <AddFriendModal open={showAddModal} onOpenChange={setShowAddModal} />
      <FriendRequestsModal open={showRequestsModal} onOpenChange={setShowRequestsModal} />
    </div>
  )
}
