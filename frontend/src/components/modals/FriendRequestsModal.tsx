import React, { useState } from 'react'
import { useChat } from '@/context/ChatContext'
import { friendApi } from '@/api/client'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Check, X, Clock, UserCheck, Inbox } from 'lucide-react'
import { formatTime } from '@/lib/utils'

interface FriendRequestsModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export const FriendRequestsModal: React.FC<FriendRequestsModalProps> = ({ open, onOpenChange }) => {
  const { friendRequests, refreshFriendRequests, refreshFriends, refreshConversations } = useChat()
  const [processingId, setProcessingId] = useState<number | null>(null)

  const handleRespond = async (requestId: number, action: 'accept' | 'reject') => {
    setProcessingId(requestId)
    try {
      await friendApi.respondRequest(requestId, action)
      await refreshFriendRequests()
      if (action === 'accept') {
        await refreshFriends()
        await refreshConversations()
      }
    } catch (err) {
      alert('处理好友申请失败')
    } finally {
      setProcessingId(null)
    }
  }

  const received = friendRequests.received || []
  const sent = friendRequests.sent || []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserCheck className="w-5 h-5 text-blue-600" />
            好友申请通知
          </DialogTitle>
          <DialogDescription>
            查看并处理向你发起的好友申请，或查看你发出的申请进度。
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="received" className="w-full">
          <TabsList className="grid grid-cols-2 mb-3">
            <TabsTrigger value="received" className="relative">
              收到的申请
              {received.length > 0 && (
                <span className="ml-1.5 px-1.5 py-0.2 text-[10px] bg-red-500 text-white rounded-full">
                  {received.length}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="sent">
              发出的申请 ({sent.length})
            </TabsTrigger>
          </TabsList>

          <TabsContent value="received" className="max-h-72 overflow-y-auto space-y-2 pr-1">
            {received.length > 0 ? (
              received.map((req) => (
                <div
                  key={req.id}
                  className="p-3 rounded-xl border border-slate-100 bg-white hover:border-slate-200 transition space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <Avatar className="w-9 h-9">
                        <AvatarImage src={req.avatar} />
                        <AvatarFallback className="bg-blue-100 text-blue-700 font-bold">
                          {req.nickname.slice(0, 1)}
                        </AvatarFallback>
                      </Avatar>
                      <div>
                        <div className="font-semibold text-sm text-slate-800">{req.nickname}</div>
                        <div className="text-[11px] text-slate-400">@{req.username} · {formatTime(req.created_at)}</div>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <Button
                        size="sm"
                        variant="default"
                        className="h-7 px-2.5 text-xs bg-emerald-600 hover:bg-emerald-700"
                        disabled={processingId === req.id}
                        onClick={() => handleRespond(req.id, 'accept')}
                      >
                        <Check className="w-3.5 h-3.5 mr-1" /> 同意
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-xs text-slate-500 hover:text-red-600"
                        disabled={processingId === req.id}
                        onClick={() => handleRespond(req.id, 'reject')}
                      >
                        <X className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </div>

                  {req.message && (
                    <div className="text-xs bg-slate-50 p-2 rounded-lg text-slate-600 border border-slate-100/80">
                      附加消息: {req.message}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div className="py-10 text-center text-xs text-slate-400 flex flex-col items-center justify-center gap-2">
                <Inbox className="w-8 h-8 text-slate-300" />
                <span>暂无待处理的好友申请</span>
              </div>
            )}
          </TabsContent>

          <TabsContent value="sent" className="max-h-72 overflow-y-auto space-y-2 pr-1">
            {sent.length > 0 ? (
              sent.map((req) => (
                <div
                  key={req.id}
                  className="p-3 rounded-xl border border-slate-100 bg-white flex items-center justify-between"
                >
                  <div className="flex items-center gap-2.5">
                    <Avatar className="w-9 h-9">
                      <AvatarImage src={req.avatar} />
                      <AvatarFallback className="bg-slate-100 text-slate-600 font-bold">
                        {req.nickname.slice(0, 1)}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <div className="font-semibold text-sm text-slate-800">{req.nickname}</div>
                      <div className="text-[11px] text-slate-400">申请时间: {formatTime(req.created_at)}</div>
                    </div>
                  </div>

                  <Badge variant="outline" className="flex items-center gap-1 text-slate-500 text-xs">
                    <Clock className="w-3 h-3 text-amber-500" /> 等待对方同意
                  </Badge>
                </div>
              ))
            ) : (
              <div className="py-10 text-center text-xs text-slate-400">
                暂无发出的申请记录
              </div>
            )}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
