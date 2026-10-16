import React, { useState, useEffect } from 'react'
import { groupApi } from '@/api/client'
import { useChat } from '@/context/ChatContext'
import { useAuth } from '@/context/AuthContext'
import { GroupMember } from '@/types'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Users, Crown, Shield, UserPlus, LogOut, Trash2, Check, Loader2 } from 'lucide-react'

interface GroupDetailModalProps {
  groupId: number | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export const GroupDetailModal: React.FC<GroupDetailModalProps> = ({ groupId, open, onOpenChange }) => {
  const { user } = useAuth()
  const { friends, refreshGroups, setActiveConversation } = useChat()
  
  const [group, setGroup] = useState<any | null>(null)
  const [members, setMembers] = useState<GroupMember[]>([])
  const [loading, setLoading] = useState(false)
  const [showInvite, setShowInvite] = useState(false)
  const [selectedFriendIds, setSelectedFriendIds] = useState<number[]>([])
  const [inviting, setInviting] = useState(false)

  const loadDetails = async () => {
    if (!groupId) return
    setLoading(true)
    try {
      const [gRes, mRes] = await Promise.all([
        groupApi.getGroupDetail(groupId),
        groupApi.getMembers(groupId),
      ])
      setGroup(gRes.data.group)
      setMembers(mRes.data.members)
    } catch (err) {
      console.error('Failed to load group details', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && groupId) {
      loadDetails()
      setShowInvite(false)
      setSelectedFriendIds([])
    }
  }, [open, groupId])

  if (!groupId || !group) return null

  const isOwner = group.owner_id === user?.id
  const currentMemberIds = new Set(members.map(m => m.user_id))
  // Friends available to invite (not already in group)
  const invitableFriends = friends.filter(f => !currentMemberIds.has(f.id))

  const handleToggleFriend = (fid: number) => {
    setSelectedFriendIds(prev =>
      prev.includes(fid) ? prev.filter(id => id !== fid) : [...prev, fid]
    )
  }

  const handleInviteSubmit = async () => {
    if (selectedFriendIds.length === 0) return
    setInviting(true)
    try {
      await groupApi.inviteMembers(groupId, selectedFriendIds)
      await loadDetails()
      setShowInvite(false)
      setSelectedFriendIds([])
    } catch (err) {
      alert('邀请好友失败')
    } finally {
      setInviting(false)
    }
  }

  const handleLeaveGroup = async () => {
    if (!window.confirm('确定要退出该群聊吗？')) return
    try {
      await groupApi.leaveGroup(groupId)
      await refreshGroups()
      setActiveConversation(null)
      onOpenChange(false)
    } catch (err) {
      alert('退出群聊失败')
    }
  }

  const handleDisbandGroup = async () => {
    if (!window.confirm('警告：解散群聊将清空群内所有聊天记录与成员关系，确定要解散吗？')) return
    try {
      await groupApi.disbandGroup(groupId)
      await refreshGroups()
      setActiveConversation(null)
      onOpenChange(false)
    } catch (err) {
      alert('解散群聊失败')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="w-5 h-5 text-indigo-600" />
            群聊信息与成员管理
          </DialogTitle>
          <DialogDescription>
            查看群资料、管理群成员与邀请好友入群。
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="py-12 flex justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* Header profile */}
            <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-2xl border border-slate-100">
              <Avatar className="w-14 h-14 ring-2 ring-white">
                <AvatarImage src={group.avatar} />
                <AvatarFallback className="font-bold text-lg bg-indigo-100 text-indigo-700">
                  {group.name.slice(0, 1)}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1">
                <div className="font-bold text-slate-900 flex items-center gap-2">
                  {group.name}
                  {isOwner && (
                    <Badge variant="default" className="text-[10px] h-4 bg-amber-500">
                      你是群主
                    </Badge>
                  )}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {group.description || '暂无群简介'}
                </div>
                <div className="text-[11px] text-slate-400 mt-1">
                  群成员共 {members.length} 人
                </div>
              </div>
            </div>

            {/* Invite Button */}
            {!showInvite ? (
              <div className="flex justify-between items-center">
                <span className="text-xs font-semibold text-slate-700">
                  群成员列表 ({members.length})
                </span>
                {invitableFriends.length > 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs gap-1 border-blue-200 text-blue-600 hover:bg-blue-50"
                    onClick={() => setShowInvite(true)}
                  >
                    <UserPlus className="w-3.5 h-3.5" /> 邀请好友入群
                  </Button>
                )}
              </div>
            ) : (
              <div className="p-3 bg-blue-50/60 rounded-xl border border-blue-100 space-y-2">
                <div className="flex justify-between items-center text-xs font-semibold text-blue-900">
                  <span>选择要邀请的好友 ({selectedFriendIds.length})</span>
                  <button
                    type="button"
                    onClick={() => setShowInvite(false)}
                    className="text-slate-400 hover:text-slate-600"
                  >
                    取消
                  </button>
                </div>
                <div className="max-h-36 overflow-y-auto space-y-1">
                  {invitableFriends.map(f => {
                    const isSelected = selectedFriendIds.includes(f.id)
                    return (
                      <div
                        key={f.id}
                        onClick={() => handleToggleFriend(f.id)}
                        className={`flex items-center justify-between p-2 rounded-lg cursor-pointer transition text-xs ${
                          isSelected ? 'bg-blue-100/70 font-medium' : 'hover:bg-white'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <Avatar className="w-6 h-6">
                            <AvatarImage src={f.avatar} />
                            <AvatarFallback>{f.nickname[0]}</AvatarFallback>
                          </Avatar>
                          <span>{f.nickname}</span>
                        </div>
                        {isSelected && <Check className="w-4 h-4 text-blue-600" />}
                      </div>
                    )
                  })}
                </div>
                <Button
                  size="sm"
                  className="w-full h-8 text-xs"
                  disabled={selectedFriendIds.length === 0 || inviting}
                  onClick={handleInviteSubmit}
                >
                  {inviting ? '邀请中...' : `确认邀请 (${selectedFriendIds.length})`}
                </Button>
              </div>
            )}

            {/* Member List */}
            <div className="max-h-48 overflow-y-auto space-y-1.5 pr-1">
              {members.map(m => (
                <div
                  key={m.user_id}
                  className="flex items-center justify-between p-2 rounded-xl hover:bg-slate-50 transition"
                >
                  <div className="flex items-center gap-2.5">
                    <Avatar className="w-8 h-8" isOnline={m.is_online}>
                      <AvatarImage src={m.avatar} />
                      <AvatarFallback className="text-xs font-bold bg-slate-100 text-slate-700">
                        {m.nickname.slice(0, 1)}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <div className="text-xs font-semibold text-slate-800 flex items-center gap-1.5">
                        {m.nickname}
                        {m.user_id === user?.id && <span className="text-[10px] text-slate-400">(我)</span>}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {m.is_online ? '在线' : '离线'} · {m.bio || '极客生活'}
                      </div>
                    </div>
                  </div>

                  <div>
                    {m.role === 'owner' ? (
                      <Badge variant="default" className="text-[10px] h-5 bg-amber-500 gap-0.5">
                        <Crown className="w-2.5 h-2.5" /> 群主
                      </Badge>
                    ) : m.role === 'admin' ? (
                      <Badge variant="secondary" className="text-[10px] h-5 bg-blue-100 text-blue-700 gap-0.5">
                        <Shield className="w-2.5 h-2.5" /> 管理员
                      </Badge>
                    ) : (
                      <span className="text-[11px] text-slate-400">成员</span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Actions: Leave / Disband */}
            <div className="pt-2 border-t border-slate-100 flex justify-between gap-2">
              <Button
                variant="outline"
                size="sm"
                className="text-xs text-red-600 border-red-200 hover:bg-red-50 hover:text-red-700 gap-1"
                onClick={handleLeaveGroup}
              >
                <LogOut className="w-3.5 h-3.5" /> 退出群聊
              </Button>

              {isOwner && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="text-xs gap-1"
                  onClick={handleDisbandGroup}
                >
                  <Trash2 className="w-3.5 h-3.5" /> 解散该群
                </Button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
