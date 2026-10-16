import React, { useState } from 'react'
import { groupApi } from '@/api/client'
import { useChat } from '@/context/ChatContext'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Search, Users, Check, Loader2, ArrowRight } from 'lucide-react'

interface JoinGroupModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export const JoinGroupModal: React.FC<JoinGroupModalProps> = ({ open, onOpenChange }) => {
  const { refreshGroups, selectConversationByTarget } = useChat()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [joiningId, setJoiningId] = useState<number | null>(null)

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    try {
      const res = await groupApi.searchGroups(query.trim())
      setResults(res.data.groups)
    } catch (err) {
      console.error('Search groups failed', err)
    } finally {
      setLoading(false)
    }
  }

  const handleJoin = async (groupId: number) => {
    setJoiningId(groupId)
    try {
      await groupApi.joinGroup(groupId)
      await refreshGroups()
      onOpenChange(false)
      // Enter the group chat immediately
      await selectConversationByTarget('group', groupId)
    } catch (err: any) {
      alert(err.response?.data?.error || '加入群聊失败')
    } finally {
      setJoiningId(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Search className="w-5 h-5 text-blue-600" />
            搜索与加入群聊
          </DialogTitle>
          <DialogDescription>
            查找感兴趣的群聊并立即加入对话。
          </DialogDescription>
        </DialogHeader>

        {/* Search input */}
        <form onSubmit={handleSearch} className="flex gap-2 my-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索群名称或简介..."
              className="pl-9"
              autoFocus
            />
          </div>
          <Button type="submit" disabled={loading || !query.trim()}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : '搜索'}
          </Button>
        </form>

        {/* Results List */}
        <div className="max-h-72 overflow-y-auto space-y-2 pr-1">
          {results.length > 0 ? (
            results.map((g) => (
              <div
                key={g.id}
                className="flex items-center justify-between p-3 rounded-xl border border-slate-100 hover:bg-slate-50 transition"
              >
                <div className="flex items-center gap-3">
                  <Avatar className="w-10 h-10">
                    <AvatarImage src={g.avatar} />
                    <AvatarFallback className="bg-indigo-100 text-indigo-700 font-bold">
                      {g.name.slice(0, 1)}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <div className="font-semibold text-sm text-slate-900 flex items-center gap-2">
                      {g.name}
                      <span className="text-[11px] font-normal text-slate-400 flex items-center gap-0.5">
                        <Users className="w-3 h-3" /> {g.member_count || 1} 人
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 line-clamp-1">
                      {g.description || '暂无群简介'}
                    </div>
                  </div>
                </div>

                <div>
                  {g.is_member ? (
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-xs h-7 gap-1"
                      onClick={() => {
                        onOpenChange(false)
                        selectConversationByTarget('group', g.id)
                      }}
                    >
                      已在群内 <ArrowRight className="w-3 h-3" />
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="default"
                      className="text-xs h-7"
                      disabled={joiningId === g.id}
                      onClick={() => handleJoin(g.id)}
                    >
                      {joiningId === g.id ? '加入中...' : '加入群聊'}
                    </Button>
                  )}
                </div>
              </div>
            ))
          ) : query && !loading ? (
            <div className="text-center py-8 text-xs text-slate-400">
              未找到相关群聊，你可以点击“创建新群聊”
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}
