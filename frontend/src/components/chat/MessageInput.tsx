import React, { useState, useRef } from 'react'
import { useChat } from '@/context/ChatContext'
import { Button } from '@/components/ui/button'
import { Send, Image as ImageIcon, Paperclip, Smile, Loader2 } from 'lucide-react'

const QUICK_EMOJIS = ['👍', '❤️', '😄', '🎉', '🚀', '🔥', '👏', '💡', '😂', '🥳', '✨', '🤝', '☕️', '💯']

export const MessageInput: React.FC<{ onImageClick?: (url: string) => void }> = () => {
  const { sendMessage, sendMediaMessage } = useChat()
  const [content, setContent] = useState('')
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleSend = async () => {
    const trimmed = content.trim()
    if (!trimmed) return
    setContent('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    await sendMessage(trimmed, 'text')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleAutoResize = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setContent(e.target.value)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`
    }
  }

  const triggerFileUpload = (type: 'image' | 'file') => {
    if (fileInputRef.current) {
      fileInputRef.current.accept = type === 'image' ? 'image/*' : '*'
      fileInputRef.current.click()
    }
  }

  const handlePaste = async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile()
        if (file) {
          e.preventDefault()
          setIsUploading(true)
          try {
            await sendMediaMessage(file)
          } finally {
            setIsUploading(false)
          }
          return
        }
      }
    }
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploading(true)
    try {
      await sendMediaMessage(file)
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="p-3 bg-white border-t border-slate-100 relative">
      {/* Hidden file input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
      />

      {/* Emoji Picker Popover */}
      {showEmojiPicker && (
        <div className="absolute bottom-16 left-4 z-20 bg-white rounded-2xl shadow-xl border border-slate-100 p-2.5 w-64 animate-in fade-in zoom-in-95">
          <div className="flex justify-between items-center mb-2 px-1 text-[11px] font-semibold text-slate-400">
            <span>常用表情</span>
            <button
              onClick={() => setShowEmojiPicker(false)}
              className="text-slate-400 hover:text-slate-600 text-xs"
            >
              ✕
            </button>
          </div>
          <div className="grid grid-cols-7 gap-1">
            {QUICK_EMOJIS.map((emoji) => (
              <button
                key={emoji}
                type="button"
                onClick={() => {
                  setContent((prev) => prev + emoji)
                  setShowEmojiPicker(false)
                  textareaRef.current?.focus()
                }}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 flex items-center justify-center text-lg transition"
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-1 mb-2 px-1">
        <button
          type="button"
          onClick={() => setShowEmojiPicker(!showEmojiPicker)}
          className="p-1.5 rounded-lg text-slate-500 hover:text-blue-600 hover:bg-slate-100 transition"
          title="插入表情"
        >
          <Smile className="w-5 h-5" />
        </button>

        <button
          type="button"
          onClick={() => triggerFileUpload('image')}
          disabled={isUploading}
          className="p-1.5 rounded-lg text-slate-500 hover:text-blue-600 hover:bg-slate-100 transition disabled:opacity-50"
          title="发送图片 (MinIO)"
        >
          <ImageIcon className="w-5 h-5" />
        </button>

        <button
          type="button"
          onClick={() => triggerFileUpload('file')}
          disabled={isUploading}
          className="p-1.5 rounded-lg text-slate-500 hover:text-blue-600 hover:bg-slate-100 transition disabled:opacity-50"
          title="发送附件文件 (MinIO)"
        >
          <Paperclip className="w-5 h-5" />
        </button>

        {isUploading && (
          <span className="text-[11px] text-blue-600 flex items-center gap-1 ml-2 font-medium">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> 上传到 MinIO 中...
          </span>
        )}
      </div>

      {/* Input Box */}
      <div className="flex items-end gap-2 bg-slate-50 rounded-2xl p-1.5 border border-slate-200/80 focus-within:border-blue-500 focus-within:bg-white focus-within:ring-2 focus-within:ring-blue-100 transition">
        <textarea
          ref={textareaRef}
          value={content}
          onChange={handleAutoResize}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行..."
          rows={1}
          className="flex-1 bg-transparent px-2.5 py-1.5 text-sm resize-none focus:outline-none max-h-32 text-slate-800 placeholder:text-slate-400"
        />

        <Button
          size="icon"
          onClick={handleSend}
          disabled={!content.trim() || isUploading}
          className="rounded-xl h-8 w-8 bg-blue-600 hover:bg-blue-700 text-white shrink-0"
        >
          <Send className="w-4 h-4" />
        </Button>
      </div>
    </div>
  )
}
