import React, { useState } from 'react'
import { userApi, friendApi } from '@/api/client'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Search, UserPlus, Check, Clock, Loader2 } from 'lucide-react'

interface AddFriendModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export const AddFriendModal: React.FC<AddFriendModalProps> = ({ open, onOpenChange }) => {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [requestTarget, setRequestTarget] = useState<any | null>(null)
  const [requestNote, setRequestNote] = useState('你好，我想添加你为好友！')
  const [sending, setSending] = useState(false)

  const handleSearch = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    try {
      const res = await userApi.searchUsers(query.trim())
      setResults(res.data.users)
    } catch (err) {
      console.error('Search users failed', err)
    } finally {
      setLoading(false)
    }
  }

  const handleSendRequest = async () => {
    if (!requestTarget) return
    setSending(true)
    try {
      await friendApi.sendRequest(requestTarget.id, requestNote)
      // Update local item
      setResults(prev =>
        prev.map(u => (u.id === requestTarget.id ? { ...u, request_sent: true } : u))
      )
      setRequestTarget(null)
      alert('好友申请已发送！')
    } catch (err: any) {
      alert(err.response?.data?.error || '发送好友申请失败')
    } finally {
      setSending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>添加新好友</DialogTitle>
          <DialogDescription>
            通过用户名或昵称搜索用户并发送好友申请。
          </DialogDescription>
        </DialogHeader>

        {/* Search input */}
        <form onSubmit={handleSearch} className="flex gap-2 my-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索用户名或昵称..."
              className="pl-9"
              autoFocus
            />
          </div>
          <Button type="submit" disabled={loading || !query.trim()}>
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : '搜索'}
          </Button>
        </form>

        {/* Results List */}
        <div className="max-h-64 overflow-y-auto space-y-2 pr-1">
          {results.length > 0 ? (
            results.map((u) => (
              <div
                key={u.id}
                className="flex items-center justify-between p-3 rounded-xl border border-slate-100 hover:bg-slate-50 transition"
              >
                <div className="flex items-center gap-3">
                  <Avatar className="w-10 h-10">
                    <AvatarImage src={u.avatar} />
                    <AvatarFallback className="font-semibold bg-blue-100 text-blue-700">
                      {u.nickname.slice(0, 1)}
                    </AvatarFallback>
                  </Avatar>
                  <div>
                    <div className="font-semibold text-sm text-slate-900 flex items-center gap-1.5">
                      {u.nickname}
                      <span className="text-xs font-normal text-slate-400">@{u.username}</span>
                    </div>
                    <div className="text-xs text-slate-500 line-clamp-1">
                      {u.bio || '暂无个性签名'}
                    </div>
                  </div>
                </div>

                <div>
                  {u.is_friend ? (
                    <Badge variant="secondary" className="flex items-center gap-1">
                      <Check className="w-3 h-3 text-emerald-600" /> 已是好友
                    </Badge>
                  ) : u.request_sent ? (
                    <Badge variant="outline" className="flex items-center gap-1 text-slate-500">
                      <Clock className="w-3 h-3" /> 已申请
                    </Badge>
                  ) : (
                    <Button
                      size="sm"
                      variant="default"
                      onClick={() => {
                        setRequestTarget(u)
                        setRequestNote(`你好，我是想要添加你为好友！`)
                      }}
                      className="flex items-center gap-1 text-xs"
                    >
                      <UserPlus className="w-3.5 h-3.5" /> 加好友
                    </Button>
                  )}
                </div>
              </div>
            ))
          ) : query && !loading ? (
            <div className="text-center py-8 text-xs text-slate-400">
              未找到匹配的用户
            </div>
          ) : null}
        </div>

        {/* Prompt note dialog overlay if requestTarget is selected */}
        {requestTarget && (
          <div className="mt-2 p-3 bg-blue-50/70 border border-blue-200 rounded-xl space-y-2">
            <div className="text-xs font-semibold text-blue-900">
              向「{requestTarget.nickname}」发送好友申请
            </div>
            <Input
              value={requestNote}
              onChange={(e) => setRequestNote(e.target.value)}
              placeholder="填写验证信息..."
              className="bg-white text-xs"
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setRequestTarget(null)}>
                取消
              </Button>
              <Button size="sm" onClick={handleSendRequest} disabled={sending}>
                {sending ? '发送中...' : '确认发送'}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
