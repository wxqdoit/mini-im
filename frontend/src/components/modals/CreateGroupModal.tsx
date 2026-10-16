import React, { useState, useRef } from 'react'
import { groupApi, uploadApi } from '@/api/client'
import { useChat } from '@/context/ChatContext'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Users, Camera, Loader2 } from 'lucide-react'

interface CreateGroupModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export const CreateGroupModal: React.FC<CreateGroupModalProps> = ({ open, onOpenChange }) => {
  const { refreshGroups, selectConversationByTarget } = useChat()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [avatar, setAvatar] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploading(true)
    try {
      const res = await uploadApi.uploadFile(file, 'avatars')
      setAvatar(res.data.url)
    } catch (err) {
      alert('群头像上传失败')
    } finally {
      setIsUploading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setIsSubmitting(true)
    try {
      const res = await groupApi.createGroup({
        name: name.trim(),
        description: description.trim(),
        avatar: avatar || `https://api.dicebear.com/7.x/shapes/svg?seed=${encodeURIComponent(name)}`,
      })
      await refreshGroups()
      onOpenChange(false)
      setName('')
      setDescription('')
      setAvatar('')
      // Switch to newly created group
      await selectConversationByTarget('group', res.data.group.id)
    } catch (err: any) {
      alert(err.response?.data?.error || '创建群组失败')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="w-5 h-5 text-blue-600" />
            创建新群聊
          </DialogTitle>
          <DialogDescription>
            创建一个属于你和朋友们的技术讨论组或兴趣群聊。
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          {/* Avatar Upload */}
          <div className="flex flex-col items-center justify-center gap-2">
            <div
              className="relative group cursor-pointer"
              onClick={() => fileInputRef.current?.click()}
            >
              <Avatar className="w-16 h-16 ring-2 ring-slate-100">
                <AvatarImage src={avatar} />
                <AvatarFallback className="bg-indigo-100 text-indigo-700 font-bold">
                  {name ? name.slice(0, 1) : <Users className="w-6 h-6" />}
                </AvatarFallback>
              </Avatar>
              <div className="absolute inset-0 bg-black/40 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-white">
                {isUploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Camera className="w-4 h-4" />}
              </div>
            </div>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleAvatarUpload}
              accept="image/*"
              className="hidden"
            />
            <span className="text-[11px] text-slate-400">设置群组头像 (可选)</span>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-700">群聊名称 *</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：全栈工程师交流、周末爬山分队"
              required
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-700">群简介</label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简要介绍这个群聊的主题与规则..."
            />
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button type="submit" disabled={isSubmitting || !name.trim()}>
              {isSubmitting ? '创建中...' : '立即创建'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
