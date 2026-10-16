import React, { useState } from 'react'
import { useChat } from '@/context/ChatContext'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Users, Plus, Search, MessageSquare, Compass } from 'lucide-react'
import { CreateGroupModal } from '../modals/CreateGroupModal'
import { JoinGroupModal } from '../modals/JoinGroupModal'

export const GroupsView: React.FC = () => {
  const { groups, selectConversationByTarget } = useChat()
  const [query, setQuery] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showJoinModal, setShowJoinModal] = useState(false)

  const filtered = groups.filter(g =>
    g.name.toLowerCase().includes(query.toLowerCase()) ||
    (g.description && g.description.toLowerCase().includes(query.toLowerCase()))
  )

  return (
    <div className="w-80 h-full bg-white border-r border-slate-100 flex flex-col shrink-0">
      {/* Header with actions */}
      <div className="p-4 border-b border-slate-100/80 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-900">群组大厅</h2>
          <span className="text-xs text-slate-400 font-medium">已加入 {groups.length} 个群</span>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Button
            size="sm"
            variant="default"
            className="text-xs h-8 gap-1 rounded-xl bg-indigo-600 hover:bg-indigo-700"
            onClick={() => setShowCreateModal(true)}
          >
            <Plus className="w-3.5 h-3.5" /> 创建群聊
          </Button>

          <Button
            size="sm"
            variant="outline"
            className="text-xs h-8 gap-1 rounded-xl"
            onClick={() => setShowJoinModal(true)}
          >
            <Search className="w-3.5 h-3.5" /> 发现群聊
          </Button>
        </div>

        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索已加入的群聊..."
            className="pl-9 h-9 bg-slate-50 border-slate-200/80 rounded-xl text-xs"
          />
        </div>
      </div>

      {/* Group Items */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-50">
        {filtered.length > 0 ? (
          filtered.map(g => (
            <div
              key={g.id}
              onClick={() => selectConversationByTarget('group', g.id)}
              className="p-3.5 flex items-center justify-between hover:bg-slate-50/80 cursor-pointer transition select-none"
            >
              <div className="flex items-center gap-3">
                <Avatar className="w-10 h-10 ring-2 ring-slate-50">
                  <AvatarImage src={g.avatar} />
                  <AvatarFallback className="bg-indigo-100 text-indigo-700 font-bold">
                    {g.name.slice(0, 1)}
                  </AvatarFallback>
                </Avatar>
                <div>
                  <div className="font-semibold text-sm text-slate-800 flex items-center gap-1.5">
                    {g.name}
                    {g.role === 'owner' && (
                      <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-amber-100 text-amber-700 font-medium">
                        群主
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-400 truncate max-w-[140px]">
                    {g.description || `${g.member_count || 1} 位成员`}
                  </div>
                </div>
              </div>

              <Button size="icon" variant="ghost" className="h-8 w-8 text-slate-400 hover:text-indigo-600">
                <MessageSquare className="w-4 h-4" />
              </Button>
            </div>
          ))
        ) : (
          <div className="py-20 text-center text-xs text-slate-400 flex flex-col items-center justify-center gap-2">
            <Compass className="w-8 h-8 text-slate-200" />
            <span>暂未加入任何群聊</span>
          </div>
        )}
      </div>

      <CreateGroupModal open={showCreateModal} onOpenChange={setShowCreateModal} />
      <JoinGroupModal open={showJoinModal} onOpenChange={setShowJoinModal} />
    </div>
  )
}
