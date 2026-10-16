import React, { useState, useRef } from 'react'
import { useAuth } from '@/context/AuthContext'
import { uploadApi } from '@/api/client'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { Camera, Loader2, Check } from 'lucide-react'

interface ProfileModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export const ProfileModal: React.FC<ProfileModalProps> = ({ open, onOpenChange }) => {
  const { user, updateProfile } = useAuth()
  
  const [nickname, setNickname] = useState(user?.nickname || '')
  const [bio, setBio] = useState(user?.bio || '')
  const [status, setStatus] = useState(user?.status || 'online')
  const [avatar, setAvatar] = useState(user?.avatar || '')
  const [isUploading, setIsUploading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [savedSuccess, setSavedSuccess] = useState(false)

  const fileInputRef = useRef<HTMLInputElement>(null)

  // Sync state when opened
  React.useEffect(() => {
    if (user && open) {
      setNickname(user.nickname)
      setBio(user.bio || '')
      setStatus(user.status || 'online')
      setAvatar(user.avatar || '')
      setSavedSuccess(false)
    }
  }, [user, open])

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploading(true)
    try {
      const res = await uploadApi.uploadFile(file, 'avatars')
      setAvatar(res.data.url)
    } catch (err) {
      alert('头像上传失败，请重试')
    } finally {
      setIsUploading(false)
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSaving(true)
    try {
      await updateProfile({ nickname, bio, avatar, status })
      setSavedSuccess(true)
      setTimeout(() => {
        onOpenChange(false)
        setSavedSuccess(false)
      }, 800)
    } catch (err) {
      alert('保存个人资料失败')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>编辑个人资料</DialogTitle>
          <DialogDescription>
            修改你的昵称、头像和个性签名，这些信息将同步给所有好友。
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSave} className="space-y-4 py-2">
          {/* Avatar Section */}
          <div className="flex flex-col items-center justify-center gap-3">
            <div className="relative group cursor-pointer" onClick={() => fileInputRef.current?.click()}>
              <Avatar className="w-20 h-20 ring-4 ring-slate-100">
                <AvatarImage src={avatar} />
                <AvatarFallback className="text-xl font-bold bg-blue-100 text-blue-700">
                  {nickname.slice(0, 2).toUpperCase() || 'U'}
                </AvatarFallback>
              </Avatar>
              <div className="absolute inset-0 bg-black/40 rounded-full flex flex-col items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity text-white text-xs">
                {isUploading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Camera className="w-5 h-5 mb-0.5" />}
                <span>更换头像</span>
              </div>
            </div>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleAvatarUpload}
              accept="image/*"
              className="hidden"
            />
            <span className="text-xs text-slate-400">点击头像上传至 MinIO 对象存储</span>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-700">昵称</label>
            <Input
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              placeholder="输入你的昵称"
              required
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-700">个性签名</label>
            <Input
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              placeholder="一句话介绍自己"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold text-slate-700">在线状态</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="flex h-9 w-full rounded-lg border border-slate-200 bg-white px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="online">🟢 在线 (Online)</option>
              <option value="busy">🔴 忙碌 (Busy)</option>
              <option value="away">🟡 离开 (Away)</option>
            </select>
          </div>

          <div className="pt-3 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button type="submit" disabled={isSaving || isUploading}>
              {savedSuccess ? (
                <span className="flex items-center gap-1 text-emerald-100">
                  <Check className="w-4 h-4" /> 已保存
                </span>
              ) : isSaving ? (
                '保存中...'
              ) : (
                '保存修改'
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
