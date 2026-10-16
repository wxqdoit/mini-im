import React, { useRef, useEffect, useState, useCallback } from 'react'
import { useChat } from '@/context/ChatContext'
import { useAuth } from '@/context/AuthContext'
import { ChatHeader } from './ChatHeader'
import { MessageBubble } from './MessageBubble'
import { MessageInput } from './MessageInput'
import { ImagePreviewModal } from '../modals/ImagePreviewModal'
import { MessageSquare } from 'lucide-react'

export const ChatWindow: React.FC = () => {
  const { activeConversation, messages } = useChat()
  const { user } = useAuth()
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [previewImageUrl, setPreviewImageUrl] = useState<string | null>(null)

  // Track if view should stay pinned to bottom
  const shouldAutoScrollRef = useRef<boolean>(true)
  const prevMessagesLengthRef = useRef<number>(messages.length)

  // Fast & robust bottom scrolling
  const scrollToBottom = useCallback((smooth = false) => {
    const container = scrollContainerRef.current
    if (!container) return

    if (smooth) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: 'smooth',
      })
    } else {
      container.scrollTop = container.scrollHeight
    }

    // Double-check with rAF to guarantee DOM layout calculation is accounted for
    requestAnimationFrame(() => {
      if (scrollContainerRef.current) {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight
      }
    })
  }, [])

  // Auto scroll to bottom on message list changes
  useEffect(() => {
    const isNew = messages.length > prevMessagesLengthRef.current
    prevMessagesLengthRef.current = messages.length

    const lastMsg = messages[messages.length - 1]
    const isSentByMe = lastMsg && (lastMsg.id < 0 || lastMsg.sender_id === user?.id)

    // If sent by me, force pinned auto-scroll; otherwise check shouldAutoScroll
    if (isSentByMe || shouldAutoScrollRef.current || !isNew) {
      shouldAutoScrollRef.current = true
      scrollToBottom(false)
    }
  }, [messages, user?.id, scrollToBottom])

  // Reset scroll to bottom when switching active conversation
  useEffect(() => {
    shouldAutoScrollRef.current = true
    prevMessagesLengthRef.current = 0
    scrollToBottom(false)
  }, [activeConversation?.conversation_id, scrollToBottom])

  // Observe inner content resize (e.g. image finished downloading & decoding, layout shifts)
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return

    const resizeObserver = new ResizeObserver(() => {
      if (shouldAutoScrollRef.current) {
        container.scrollTop = container.scrollHeight
      }
    })

    const contentEl = container.firstElementChild
    if (contentEl) {
      resizeObserver.observe(contentEl)
    }

    return () => resizeObserver.disconnect()
  }, [])

  // Callback when media image finishes loading
  const handleMediaLoad = useCallback(() => {
    if (shouldAutoScrollRef.current) {
      scrollToBottom(false)
    }
  }, [scrollToBottom])

  // Track user scroll position
  const handleScroll = () => {
    const container = scrollContainerRef.current
    if (!container) return
    const { scrollTop, scrollHeight, clientHeight } = container
    // Within 120px of bottom is considered pinned to bottom
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 120
    shouldAutoScrollRef.current = isNearBottom
  }

  if (!activeConversation) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 bg-slate-50/50 text-center select-none">
        <div className="w-20 h-20 rounded-3xl bg-blue-100/60 text-blue-600 flex items-center justify-center mb-6 shadow-xs">
          <MessageSquare className="w-10 h-10" />
        </div>
        <h2 className="text-xl font-bold text-slate-800">欢迎使用 Mini IM 全栈即时通讯</h2>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-50/40 relative overflow-hidden">
      {/* Top Header */}
      <ChatHeader />

      {/* Message Feed */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-6 space-y-2"
      >
        <div className="space-y-2">
          {messages.length > 0 ? (
            messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                onImageClick={(url) => setPreviewImageUrl(url)}
                onMediaLoad={handleMediaLoad}
              />
            ))
          ) : (
            <div className="text-center py-20 text-xs text-slate-400 select-none">
              开始向 {activeConversation.name} 发送第一条消息吧 💬
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Message Input */}
      <MessageInput onImageClick={(url) => setPreviewImageUrl(url)} />

      {/* Fullscreen Image Lightbox Modal */}
      <ImagePreviewModal
        url={previewImageUrl}
        open={!!previewImageUrl}
        onOpenChange={(open) => !open && setPreviewImageUrl(null)}
      />
    </div>
  )
}
