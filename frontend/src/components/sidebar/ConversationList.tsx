import React, { useState } from 'react'
import { useChat } from '@/context/ChatContext'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import { Search, MessageSquare, Plus } from 'lucide-react'
import { formatTime } from '@/lib/utils'

export const ConversationList: React.FC = () => {
  const { conversations, activeConversation, setActiveConversation } = useChat()
  const [query, setQuery] = useState('')

  const filtered = conversations.filter(c =>
    c.name.toLowerCase().includes(query.toLowerCase()) ||
    (c.last_message && c.last_message.toLowerCase().includes(query.toLowerCase()))
  )

  return (
    <div className="w-80 h-full bg-white border-r border-slate-100 flex flex-col shrink-0">
      {/* Header */}
      <div className="p-4 border-b border-slate-100/80">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold text-slate-900">消息列表</h2>
          <span className="text-xs text-slate-400 font-medium">{conversations.length} 个会话</span>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索消息或联系人..."
            className="pl-9 h-9 bg-slate-50 border-slate-200/80 rounded-xl text-xs"
          />
        </div>
      </div>

      {/* Conversation Items */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-50">
        {filtered.length > 0 ? (
          filtered.map((conv) => {
            const isActive = activeConversation?.conversation_id === conv.conversation_id
            const isGroup = conv.type === 'group'

            return (
              <div
                key={conv.conversation_id}
                onClick={() => setActiveConversation(conv)}
                className={`p-3.5 flex items-center gap-3 cursor-pointer transition select-none ${
                  isActive
                    ? 'bg-blue-50/70 border-r-2 border-blue-600'
                    : 'hover:bg-slate-50/80'
                }`}
              >
                <Avatar
                  className="w-11 h-11 shrink-0 ring-2 ring-slate-50"
                  isOnline={!isGroup ? conv.is_online : undefined}
                >
                  <AvatarImage src={conv.avatar} />
                  <AvatarFallback className={`font-semibold ${isGroup ? 'bg-indigo-100 text-indigo-700' : 'bg-blue-100 text-blue-700'}`}>
                    {conv.name.slice(0, 1)}
                  </AvatarFallback>
                </Avatar>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="font-semibold text-sm text-slate-800 truncate">
                      {conv.name}
                    </span>
                    <span className="text-[10px] text-slate-400 shrink-0">
                      {formatTime(conv.last_time)}
                    </span>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-400 truncate max-w-[160px]">
                      {conv.last_message || '暂无新消息'}
                    </span>
                    {conv.unread_count > 0 && (
                      <span className="ml-1 px-1.5 py-0.2 rounded-full bg-blue-600 text-white text-[10px] font-bold">
                        {conv.unread_count}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )
          })
        ) : (
          <div className="py-20 text-center text-xs text-slate-400 flex flex-col items-center justify-center gap-2">
            <MessageSquare className="w-8 h-8 text-slate-200" />
            <span>暂无聊天会话</span>
          </div>
        )}
      </div>
    </div>
  )
}
