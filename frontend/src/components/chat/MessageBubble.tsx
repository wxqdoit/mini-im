import React from 'react'
import { Message } from '@/types'
import { useAuth } from '@/context/AuthContext'
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar'
import { formatTime, formatFileSize } from '@/lib/utils'
import { FileText, Download, Image as ImageIcon, Loader2, Lock } from 'lucide-react'

interface MessageBubbleProps {
  message: Message
  onImageClick?: (url: string) => void
  onMediaLoad?: () => void
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message, onImageClick, onMediaLoad }) => {
  const { user } = useAuth()
  const isMe = message.sender_id === user?.id

  return (
    <div className={`flex gap-3 mb-4 group ${isMe ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <Avatar className="w-8 h-8 shrink-0 select-none">
        <AvatarImage src={isMe ? user?.avatar : message.sender?.avatar} />
        <AvatarFallback className={`text-xs font-semibold ${isMe ? 'bg-blue-600 text-white' : 'bg-slate-200 text-slate-700'}`}>
          {(isMe ? user?.nickname : message.sender?.nickname || 'U')?.slice(0, 1)}
        </AvatarFallback>
      </Avatar>

      {/* Bubble + Meta */}
      <div className={`flex flex-col max-w-[70%] ${isMe ? 'items-end' : 'items-start'}`}>
        {/* Sender name for group chat if not me */}
        {!isMe && message.conversation_type === 'group' && (
          <span className="text-[11px] text-slate-400 mb-1 px-1 font-medium">
            {message.sender?.nickname || '未知成员'}
          </span>
        )}

        {/* Message Content */}
        {message.msg_type === 'text' && (
          <div
            className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed shadow-xs break-words whitespace-pre-wrap ${
              isMe
                ? 'bg-blue-600 text-white rounded-tr-none'
                : 'bg-white border border-slate-100 text-slate-800 rounded-tl-none'
            }`}
          >
            {message.content}
          </div>
        )}

        {message.msg_type === 'image' && (
          <div
            className={`relative rounded-2xl overflow-hidden border border-slate-100/80 shadow-xs cursor-pointer bg-slate-100 min-w-[140px] min-h-[140px] flex items-center justify-center ${
              isMe ? 'rounded-tr-none' : 'rounded-tl-none'
            }`}
            onClick={() => onImageClick && message.media_url && onImageClick(message.media_url)}
          >
            {message.media_url ? (
              <img
                src={message.media_url}
                alt="Uploaded media"
                className="max-h-60 max-w-xs object-cover rounded-2xl hover:opacity-95 transition"
                loading="eager"
                onLoad={() => onMediaLoad?.()}
              />
            ) : (
              <div className="w-32 h-32 flex items-center justify-center text-slate-300">
                <ImageIcon className="w-8 h-8" />
              </div>
            )}

            {message.is_uploading && (
              <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[1px] flex flex-col items-center justify-center text-white text-xs gap-1.5 font-medium rounded-2xl">
                <Loader2 className="w-5 h-5 animate-spin text-white" />
                <span>上传中...</span>
              </div>
            )}
          </div>
        )}

        {message.msg_type === 'file' && (
          <div
            className={`p-3 rounded-2xl flex items-center gap-3 border shadow-xs ${
              isMe
                ? 'bg-blue-600 text-white border-blue-500 rounded-tr-none'
                : 'bg-white text-slate-800 border-slate-200 rounded-tl-none'
            }`}
          >
            <div className={`p-2.5 rounded-xl ${isMe ? 'bg-white/20' : 'bg-blue-50 text-blue-600'}`}>
              <FileText className="w-5 h-5" />
            </div>
            <div className="flex-1 min-w-0 pr-2">
              <div className="text-xs font-semibold truncate">{message.file_name || '附件文件'}</div>
              <div className={`text-[10px] ${isMe ? 'text-blue-100' : 'text-slate-400'}`}>
                {formatFileSize(message.file_size)}
              </div>
            </div>
            {message.is_uploading ? (
              <Loader2 className={`w-4 h-4 animate-spin ${isMe ? 'text-white' : 'text-blue-600'}`} />
            ) : (
              message.media_url && (
                <a
                  href={message.media_url}
                  target="_blank"
                  rel="noreferrer"
                  download={message.file_name}
                  className={`p-2 rounded-lg transition ${
                    isMe ? 'hover:bg-white/20 text-white' : 'hover:bg-slate-100 text-slate-600'
                  }`}
                  title="下载文件"
                >
                  <Download className="w-4 h-4" />
                </a>
              )
            )}
          </div>
        )}

        {/* Timestamp & E2EE Indicator */}
        <div className="flex items-center gap-1.5 mt-1 px-1">
          {message.is_encrypted && (
            <span
              className="inline-flex items-center gap-0.5 text-[9px] text-emerald-600 bg-emerald-50 px-1 py-0.2 rounded border border-emerald-200/50 select-none"
              title="端到端加密保护 (ECDH P-256 + AES-256-GCM)"
            >
              <Lock className="w-2.5 h-2.5" />
              <span>E2EE</span>
            </span>
          )}
          <span className="text-[10px] text-slate-400 opacity-70 group-hover:opacity-100 transition-opacity">
            {formatTime(message.created_at)}
          </span>
        </div>
      </div>
    </div>
  )
}
