import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { User, Friend, FriendRequest, Group, Message, Conversation } from '../types'
import { friendApi, groupApi, messageApi, uploadApi } from '../api/client'
import { useAuth } from './AuthContext'
import { playNotificationSound } from '../lib/utils'
import {
  initUserE2EE,
  encryptDirectMessage,
  decryptDirectMessage,
  encryptGroupMessage,
  decryptGroupMessage,
} from '../lib/crypto'


interface ChatContextType {
  conversations: Conversation[]
  activeConversation: Conversation | null
  setActiveConversation: (conv: Conversation | null) => void
  messages: Message[]
  friends: Friend[]
  friendRequests: { received: FriendRequest[]; sent: FriendRequest[] }
  groups: Group[]
  wsStatus: 'connecting' | 'connected' | 'disconnected'
  
  sendMessage: (
    content: string,
    msg_type?: 'text' | 'image' | 'file',
    media_url?: string,
    file_name?: string,
    file_size?: number
  ) => Promise<void>
  sendMediaMessage: (file: File) => Promise<void>
  
  refreshConversations: () => Promise<void>
  refreshFriends: () => Promise<void>
  refreshGroups: () => Promise<void>
  refreshFriendRequests: () => Promise<void>
  selectConversationByTarget: (type: 'direct' | 'group', targetId: number) => Promise<void>
}

const ChatContext = createContext<ChatContextType | undefined>(undefined)

export const ChatProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, token } = useAuth()
  
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [friends, setFriends] = useState<Friend[]>([])
  const [friendRequests, setFriendRequests] = useState<{ received: FriendRequest[]; sent: FriendRequest[] }>({
    received: [],
    sent: [],
  })
  const [groups, setGroups] = useState<Group[]>([])
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected')

  // Refs to avoid stale closures in event handlers and timers
  const activeConversationRef = useRef<Conversation | null>(activeConversation)
  const userRef = useRef<User | null>(user)
  const tokenRef = useRef<string | null>(token)
  const wsRef = useRef<WebSocket | null>(null)
  const pingIntervalRef = useRef<any>(null)
  const reconnectTimeoutRef = useRef<any>(null)
  const isLoggingOutRef = useRef<boolean>(false)
  const processedMsgIdsRef = useRef<Set<number>>(new Set())

  // Initialize E2EE Keys
  useEffect(() => {
    if (user?.id) {
      initUserE2EE(user.id).catch(err => console.warn('[E2EE] Init warning:', err))
    }
  }, [user?.id])

  // Keep refs synchronized
  useEffect(() => {
    activeConversationRef.current = activeConversation
  }, [activeConversation])

  useEffect(() => {
    userRef.current = user
  }, [user])

  useEffect(() => {
    tokenRef.current = token
  }, [token])

  const setConversationWithRef = useCallback((conv: Conversation | null) => {
    activeConversationRef.current = conv
    setActiveConversation(conv)
    if (conv) {
      setConversations(prev =>
        prev.map(c =>
          c.conversation_id === conv.conversation_id
            ? { ...c, unread_count: 0 }
            : c
        )
      )
      if (conv.type === 'direct') {
        messageApi.markRead(conv.target_id).catch(() => {})
      }
    }
  }, [])

  // 1. Data Refresh Functions
  const refreshFriends = useCallback(async () => {
    if (!tokenRef.current) return
    try {
      const res = await friendApi.getFriends()
      setFriends(res.data.friends)
    } catch (err) {
      console.error('Failed to load friends', err)
    }
  }, [])

  const refreshGroups = useCallback(async () => {
    if (!tokenRef.current) return
    try {
      const res = await groupApi.getMyGroups()
      setGroups(res.data.groups)
    } catch (err) {
      console.error('Failed to load groups', err)
    }
  }, [])

  const refreshFriendRequests = useCallback(async () => {
    if (!tokenRef.current) return
    try {
      const res = await friendApi.getRequests()
      setFriendRequests(res.data)
    } catch (err) {
      console.error('Failed to load friend requests', err)
    }
  }, [])

  const refreshConversations = useCallback(async () => {
    if (!tokenRef.current) return
    try {
      const res = await messageApi.getConversations()
      setConversations(res.data.conversations)
    } catch (err) {
      console.error('Failed to load conversations', err)
    }
  }, [])

  // 2. Load Message History when Active Conversation Changes
  useEffect(() => {
    if (!activeConversation || !token) {
      setMessages([])
      return
    }

    const fetchHistory = async () => {
      try {
        const res = await messageApi.getHistory(activeConversation.type, activeConversation.target_id)
        const rawList = res.data.messages || []
        const currentUid = userRef.current?.id || 0
        const decryptedList = await Promise.all(
          rawList.map(async (m) => {
            if (m.is_encrypted && m.msg_type === 'text') {
              if (activeConversation.type === 'direct') {
                const dec = await decryptDirectMessage(currentUid, m)
                return { ...m, content: dec }
              } else {
                const dec = await decryptGroupMessage(activeConversation.target_id, m)
                return { ...m, content: dec }
              }
            }
            return m
          })
        )
        setMessages(decryptedList)
        
        // Clear unread count for current conversation (both direct and group)
        setConversations(prev =>
          prev.map(c =>
            c.conversation_id === activeConversation.conversation_id
              ? { ...c, unread_count: 0 }
              : c
          )
        )
        if (activeConversation.type === 'direct') {
          messageApi.markRead(activeConversation.target_id).catch(() => {})
        }
      } catch (err) {
        console.error('Failed to load message history', err)
      }
    }

    fetchHistory()
  }, [activeConversation?.conversation_id, token])

  // 3. Open conversation helper
  const selectConversationByTarget = async (type: 'direct' | 'group', targetId: number) => {
    const convId = `${type}_${targetId}`
    const existing = conversations.find(c => c.conversation_id === convId)

    if (type === 'direct') {
      const friend = friends.find(f => Number(f.id) === Number(targetId))
      const isOnline = friend?.is_online ?? existing?.is_online ?? false
      const friendStatus = friend?.status ?? existing?.status ?? (isOnline ? 'online' : 'offline')

      if (existing) {
        const updated = { ...existing, unread_count: 0, is_online: isOnline, status: friendStatus }
        setConversations(prev => prev.map(c => c.conversation_id === convId ? { ...c, unread_count: 0 } : c))
        setConversationWithRef(updated)
        return
      }

      if (friend) {
        const newConv: Conversation = {
          conversation_id: convId,
          type: 'direct',
          target_id: targetId,
          name: friend.nickname,
          avatar: friend.avatar,
          bio: friend.bio,
          is_online: isOnline,
          status: friendStatus,
          unread_count: 0,
        }
        setConversations(prev => [newConv, ...prev])
        setConversationWithRef(newConv)
      }
    } else {
      const grp = groups.find(g => Number(g.id) === Number(targetId))
      if (existing) {
        const updated = { ...existing, unread_count: 0 }
        setConversations(prev => prev.map(c => c.conversation_id === convId ? { ...c, unread_count: 0 } : c))
        setConversationWithRef(updated)
        return
      }
      if (grp) {
        const newConv: Conversation = {
          conversation_id: convId,
          type: 'group',
          target_id: targetId,
          name: grp.name,
          avatar: grp.avatar,
          description: grp.description,
          is_online: true,
          unread_count: 0,
        }
        setConversations(prev => [newConv, ...prev])
        setConversationWithRef(newConv)
      }
    }
  }

  // 4. WebSocket Event Handler
  const handleWebSocketEvent = async (payload: any) => {
    const eventName = payload.event
    const data = payload.data
    const currentActive = activeConversationRef.current
    const currentUser = userRef.current

    if (eventName === 'new_message') {
      let newMsg: Message = { ...data }
      if (!newMsg) return

      // Decrypt if E2EE protected
      if (newMsg.is_encrypted && newMsg.msg_type === 'text') {
        const curUid = currentUser?.id || 0
        if (Number(newMsg.sender_id) !== Number(curUid)) {
          if (newMsg.conversation_type === 'direct') {
            newMsg.content = await decryptDirectMessage(curUid, newMsg)
          } else {
            newMsg.content = await decryptGroupMessage(newMsg.recipient_id, newMsg)
          }
        }
      }

      // Deduplicate message ID across duplicate sockets, reconnects, or frame replays
      if (newMsg.id && processedMsgIdsRef.current.has(newMsg.id)) {
        return
      }
      if (newMsg.id && newMsg.id > 0) {
        processedMsgIdsRef.current.add(newMsg.id)
        if (processedMsgIdsRef.current.size > 1000) {
          const firstVal = processedMsgIdsRef.current.values().next().value
          if (firstVal !== undefined) processedMsgIdsRef.current.delete(firstVal)
        }
      }

      const isDirect = newMsg.conversation_type === 'direct'
      
      const isActiveDirect = isDirect && (
        (Number(newMsg.sender_id) === Number(currentActive?.target_id) && Number(newMsg.recipient_id) === Number(currentUser?.id)) ||
        (Number(newMsg.sender_id) === Number(currentUser?.id) && Number(newMsg.recipient_id) === Number(currentActive?.target_id))
      )
      const isActiveGroup = !isDirect && (Number(newMsg.recipient_id) === Number(currentActive?.target_id))

      if (isActiveDirect || isActiveGroup) {
        setMessages(prev => {
          // If optimistic message exists, replace it
          const tempIdx = prev.findIndex(m =>
            m.id < 0 &&
            Number(m.sender_id) === Number(newMsg.sender_id) &&
            m.msg_type === newMsg.msg_type &&
            (
              m.content === newMsg.content ||
              (newMsg.media_url && (m.media_url === newMsg.media_url || m.media_url?.startsWith("blob:")))
            )
          )
          if (tempIdx !== -1) {
            const copy = [...prev]
            copy[tempIdx] = newMsg
            return copy
          }
          if (prev.some(m => m.id === newMsg.id)) return prev
          return [...prev, newMsg]
        })

        if (Number(newMsg.sender_id) !== Number(currentUser?.id) && isDirect) {
          messageApi.markRead(newMsg.sender_id).catch(() => {})
        }
      }

      if (Number(newMsg.sender_id) !== Number(currentUser?.id)) {
        playNotificationSound()
      }

      const targetId = isDirect
        ? (Number(newMsg.sender_id) === Number(currentUser?.id) ? newMsg.recipient_id : newMsg.sender_id)
        : newMsg.recipient_id
      const convId = `${newMsg.conversation_type}_${targetId}`

      let preview = newMsg.content
      if (newMsg.msg_type === 'image') preview = '[图片]'
      if (newMsg.msg_type === 'file') preview = `[文件] ${newMsg.file_name || ''}`.trim()
      if (!isDirect && newMsg.sender?.nickname) {
        preview = `${newMsg.sender.nickname}: ${preview}`
      }

      setConversations(prev => {
        const existingIdx = prev.findIndex(c => c.conversation_id === convId)
        const isCurrentChat = currentActive?.conversation_id === convId
        const isFromMe = Number(newMsg.sender_id) === Number(currentUser?.id)

        if (existingIdx !== -1) {
          const item = prev[existingIdx]
          const isDuplicate = item.last_message_id === newMsg.id
          const shouldIncrement = !isCurrentChat && !isDuplicate && !isFromMe

          const updatedItem: Conversation = {
            ...item,
            last_message: preview,
            last_message_id: newMsg.id,
            last_time: newMsg.created_at || new Date().toISOString(),
            unread_count: isCurrentChat ? 0 : (item.unread_count + (shouldIncrement ? 1 : 0)),
          }
          const filtered = prev.filter((_, idx) => idx !== existingIdx)
          return [updatedItem, ...filtered]
        } else {
          // Immediate conversation item creation without waiting for HTTP
          const sender = newMsg.sender
          const newConv: Conversation = {
            conversation_id: convId,
            type: newMsg.conversation_type,
            target_id: Number(targetId),
            name: isDirect ? (sender?.nickname || sender?.username || `用户 ${targetId}`) : `群聊 ${targetId}`,
            avatar: sender?.avatar || '',
            bio: '',
            is_online: true,
            status: 'online',
            last_message: preview,
            last_message_id: newMsg.id,
            last_time: newMsg.created_at || new Date().toISOString(),
            unread_count: isCurrentChat || isFromMe ? 0 : 1,
          }
          return [newConv, ...prev]
        }
      })
    } else if (eventName === 'friend_request_received') {
      playNotificationSound()
      refreshFriendRequests()
    } else if (eventName === 'friend_request_accepted') {
      playNotificationSound()
      refreshFriends()
      refreshConversations()
    } else if (eventName === 'friend_deleted') {
      refreshFriends()
      refreshConversations()
      if (currentActive?.target_id === data.user_id && currentActive?.type === 'direct') {
        setConversationWithRef(null)
      }
    } else if (eventName === 'user_status_changed') {
      const { user_id, is_online, status } = data
      const uid = Number(user_id)
      const onlineStatus = status || (is_online ? 'online' : 'offline')
      
      // Update in friends list
      setFriends(prev =>
        prev.map(f => (Number(f.id) === uid ? { ...f, is_online, status: onlineStatus } : f))
      )
      
      // Update in conversation list
      setConversations(prev =>
        prev.map(c => (c.type === 'direct' && Number(c.target_id) === uid ? { ...c, is_online, status: onlineStatus } : c))
      )

      // Update current active conversation header immediately
      setActiveConversation(prev => {
        if (prev && prev.type === 'direct' && Number(prev.target_id) === uid) {
          const updated = { ...prev, is_online, status: onlineStatus }
          activeConversationRef.current = updated
          return updated
        }
        return prev
      })
    } else if (eventName === 'user_profile_updated') {
      const updatedUser = data.user
      const uid = Number(updatedUser.id)
      
      setFriends(prev =>
        prev.map(f => (Number(f.id) === uid ? {
          ...f,
          nickname: updatedUser.nickname || f.nickname,
          avatar: updatedUser.avatar || f.avatar,
          bio: updatedUser.bio !== undefined ? updatedUser.bio : f.bio,
          status: updatedUser.status || f.status,
          is_online: updatedUser.status !== 'offline'
        } : f))
      )

      setConversations(prev =>
        prev.map(c => (c.type === 'direct' && Number(c.target_id) === uid ? {
          ...c,
          name: updatedUser.nickname || c.name,
          avatar: updatedUser.avatar || c.avatar,
          bio: updatedUser.bio !== undefined ? updatedUser.bio : c.bio,
          status: updatedUser.status || c.status,
          is_online: updatedUser.status !== 'offline'
        } : c))
      )

      setActiveConversation(prev => {
        if (prev && prev.type === 'direct' && Number(prev.target_id) === uid) {
          const updated = {
            ...prev,
            name: updatedUser.nickname || prev.name,
            avatar: updatedUser.avatar || prev.avatar,
            bio: updatedUser.bio !== undefined ? updatedUser.bio : prev.bio,
            status: updatedUser.status || prev.status,
            is_online: updatedUser.status !== 'offline'
          }
          activeConversationRef.current = updated
          return updated
        }
        return prev
      })
    } else if (['member_joined', 'members_invited', 'member_left', 'group_disbanded'].includes(eventName)) {
      refreshGroups()
      if (eventName === 'group_disbanded' && currentActive?.target_id === data.group_id) {
        setConversationWithRef(null)
      }
    }
  }

  // Ref wrapper to ensure ws.onmessage always invokes the latest event handler
  const handleWebSocketEventRef = useRef(handleWebSocketEvent)
  useEffect(() => {
    handleWebSocketEventRef.current = handleWebSocketEvent
  })

  // 5. WebSocket Real-time Connection
  useEffect(() => {
    if (!token || !user) {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      return
    }

    let isDisposed = false
    isLoggingOutRef.current = false

    const connectWebSocket = () => {
      if (isDisposed || isLoggingOutRef.current || !tokenRef.current) return

      // Clean up previous socket completely before establishing a new one
      if (wsRef.current) {
        const oldWs = wsRef.current
        oldWs.onopen = null
        oldWs.onmessage = null
        oldWs.onerror = null
        oldWs.onclose = null
        try {
          oldWs.close(1000, "Reconnecting")
        } catch (_) {}
        wsRef.current = null
      }

      setWsStatus('connecting')
      
      const isHttps = window.location.protocol === 'https:'
      const wsProtocol = isHttps ? 'wss:' : 'ws:'
      // If running on Vite dev port 5173, directly connect to backend port 5001 for zero-proxy stability
      const wsPort = window.location.port === '5173' ? '5001' : window.location.port
      const wsHost = wsPort ? `${window.location.hostname}:${wsPort}` : window.location.host
      const wsUrl = `${wsProtocol}//${wsHost}/ws?token=${encodeURIComponent(tokenRef.current)}`

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        if (isDisposed) {
          try { ws.close(1000, "Disposed") } catch (_) {}
          return
        }
        setWsStatus('connected')
        refreshConversations()
        refreshFriends()

        // Fetch latest messages if chat is already active
        const cur = activeConversationRef.current
        if (cur) {
          messageApi.getHistory(cur.type, cur.target_id).then(res => {
            setMessages(res.data.messages)
          }).catch(() => {})
        }

        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 15000)
      }

      ws.onmessage = (event) => {
        if (isDisposed) return
        try {
          const payload = JSON.parse(event.data)
          handleWebSocketEventRef.current(payload)
        } catch (e) {
          console.error('Failed to parse WS frame', e)
        }
      }

      ws.onclose = () => {
        if (isDisposed) return
        setWsStatus('disconnected')
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
          pingIntervalRef.current = null
        }
        // Only reconnect if not logging out, not disposed, and token is still valid
        if (tokenRef.current && !isLoggingOutRef.current && !isDisposed) {
          if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current)
          reconnectTimeoutRef.current = setTimeout(() => {
            if (tokenRef.current && !isLoggingOutRef.current && !isDisposed) {
              connectWebSocket()
            }
          }, 3000)
        }
      }

      ws.onerror = (err) => {
        if (isDisposed) return
        console.warn('WebSocket error:', err)
        ws.close()
      }
    }

    connectWebSocket()

    const handleBeforeUnload = () => {
      isDisposed = true
      isLoggingOutRef.current = true
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close(1000, "Window unload")
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)

    return () => {
      isDisposed = true
      isLoggingOutRef.current = true
      window.removeEventListener('beforeunload', handleBeforeUnload)
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
        pingIntervalRef.current = null
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      if (wsRef.current) {
        const socket = wsRef.current
        socket.onopen = null
        socket.onmessage = null
        socket.onerror = null
        socket.onclose = null
        try {
          socket.close(1000, "Cleanup")
        } catch (_) {}
        wsRef.current = null
      }
    }
  }, [token, user?.id])

  // 6. Send message handler with INSTANT OPTIMISTIC UI UPDATE
  const sendMessage = async (
    content: string,
    msg_type: 'text' | 'image' | 'file' = 'text',
    media_url: string = '',
    file_name: string = '',
    file_size: number = 0
  ) => {
    const currentActive = activeConversationRef.current
    const currentUser = userRef.current
    if (!currentActive || !currentUser) return

    const nowIso = new Date().toISOString()
    const tempId = -Date.now()

    // 🔒 E2EE Encryption for text messages
    let cipherContent = content
    let isEncrypted = false
    let ivStr = ''
    let ephemeralKeyStr = ''

    if (msg_type === 'text') {
      if (currentActive.type === 'direct') {
        const enc = await encryptDirectMessage(currentUser.id, currentActive.target_id, content)
        if (enc.is_encrypted) {
          cipherContent = enc.content
          isEncrypted = true
          ivStr = enc.iv
          ephemeralKeyStr = enc.ephemeral_key
        }
      } else if (currentActive.type === 'group') {
        const enc = await encryptGroupMessage(currentActive.target_id, content)
        if (enc.is_encrypted) {
          cipherContent = enc.content
          isEncrypted = true
          ivStr = enc.iv
        }
      }
    }

    // ⚡️ Step A: Optimistic instant message update in UI (0ms delay, plaintext locally)
    const optimisticMessage: Message = {
      id: tempId,
      conversation_type: currentActive.type,
      sender_id: currentUser.id,
      recipient_id: currentActive.target_id,
      msg_type,
      content,
      is_encrypted: isEncrypted,
      iv: ivStr,
      ephemeral_key: ephemeralKeyStr,
      media_url,
      file_name,
      file_size,
      created_at: nowIso,
      is_read: false,
      sender: {
        id: currentUser.id,
        username: currentUser.username,
        nickname: currentUser.nickname,
        avatar: currentUser.avatar,
      },
    }

    setMessages(prev => [...prev, optimisticMessage])

    // ⚡️ Step B: Optimistic instant conversation list update (move to top with preview)
    let preview = content
    if (msg_type === 'image') preview = '[图片]'
    if (msg_type === 'file') preview = `[文件] ${file_name || ''}`.trim()
    if (currentActive.type === 'group') {
      preview = `${currentUser.nickname}: ${preview}`
    }

    setConversations(prev => {
      const convId = currentActive.conversation_id
      const idx = prev.findIndex(c => c.conversation_id === convId)
      if (idx !== -1) {
        const updatedItem: Conversation = {
          ...prev[idx],
          last_message: preview,
          last_time: nowIso,
        }
        const filtered = prev.filter((_, i) => i !== idx)
        return [updatedItem, ...filtered]
      } else {
        const newConv: Conversation = {
          ...currentActive,
          last_message: preview,
          last_time: nowIso,
          unread_count: 0
        }
        return [newConv, ...prev]
      }
    })

    // ⚡️ Step C: Send via WebSocket or REST to Kafka pipeline
    try {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        const frame = {
          type: 'chat_message',
          conversation_type: currentActive.type,
          recipient_id: currentActive.target_id,
          msg_type,
          content: cipherContent,
          is_encrypted: isEncrypted,
          iv: ivStr,
          ephemeral_key: ephemeralKeyStr,
          media_url,
          file_name,
          file_size,
        }
        wsRef.current.send(JSON.stringify(frame))
      } else {
        await messageApi.sendMessage({
          conversation_type: currentActive.type,
          recipient_id: currentActive.target_id,
          msg_type,
          content: cipherContent,
          is_encrypted: isEncrypted,
          iv: ivStr,
          ephemeral_key: ephemeralKeyStr,
          media_url,
          file_name,
          file_size,
        })
      }
    } catch (err) {
      console.error('Failed to dispatch message to server', err)
    }
  }

  // 7. Send media message handler with INSTANT OPTIMISTIC PREVIEW & AUTO SCROLL
  const sendMediaMessage = async (file: File) => {
    const currentActive = activeConversationRef.current
    const currentUser = userRef.current
    if (!currentActive || !currentUser) return

    const isImg = file.type.startsWith('image/')
    const msg_type: 'image' | 'file' = isImg ? 'image' : 'file'
    const localUrl = isImg ? URL.createObjectURL(file) : ''
    const nowIso = new Date().toISOString()
    const tempId = -Date.now()

    // Step A: Optimistic instant message update in UI (0ms delay)
    const optimisticMessage: Message = {
      id: tempId,
      conversation_type: currentActive.type,
      sender_id: currentUser.id,
      recipient_id: currentActive.target_id,
      msg_type,
      content: isImg ? '[图片]' : `[文件] ${file.name}`,
      media_url: localUrl,
      file_name: file.name,
      file_size: file.size,
      created_at: nowIso,
      is_read: false,
      is_uploading: true,
      sender: {
        id: currentUser.id,
        username: currentUser.username,
        nickname: currentUser.nickname,
        avatar: currentUser.avatar,
      },
    }

    setMessages(prev => [...prev, optimisticMessage])

    // Step B: Optimistic instant conversation list update
    const preview = isImg ? '[图片]' : `[文件] ${file.name}`
    setConversations(prev => {
      const convId = currentActive.conversation_id
      const idx = prev.findIndex(c => c.conversation_id === convId)
      if (idx !== -1) {
        const updatedItem: Conversation = {
          ...prev[idx],
          last_message: currentActive.type === 'group' ? `${currentUser.nickname}: ${preview}` : preview,
          last_time: nowIso,
        }
        return [updatedItem, ...prev.filter((_, i) => i !== idx)]
      } else {
        const newConv: Conversation = {
          ...currentActive,
          last_message: currentActive.type === 'group' ? `${currentUser.nickname}: ${preview}` : preview,
          last_time: nowIso,
          unread_count: 0
        }
        return [newConv, ...prev]
      }
    })

    // Step C: Upload to MinIO
    try {
      const res = await uploadApi.uploadFile(file, 'chat')
      const { url, file_name, file_size } = res.data

      // Update optimistic message with real MinIO URL and clear uploading flag
      setMessages(prev =>
        prev.map(m =>
          m.id === tempId
            ? { ...m, media_url: url, is_uploading: false, file_name: file_name || file.name, file_size: file_size || file.size }
            : m
        )
      )

      // Step D: Send via WebSocket or REST to Kafka pipeline
      const frame = {
        type: 'chat_message',
        conversation_type: currentActive.type,
        recipient_id: currentActive.target_id,
        msg_type,
        content: isImg ? '[图片]' : `[文件] ${file_name || file.name}`,
        media_url: url,
        file_name: file_name || file.name,
        file_size: file_size || file.size,
      }

      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(frame))
      } else {
        await messageApi.sendMessage(frame)
      }
    } catch (err) {
      console.error('Failed to upload/send media', err)
      setMessages(prev => prev.filter(m => m.id !== tempId))
      alert('上传媒体文件失败，请检查网络或 MinIO 服务')
    }
  }

  // Initial load when user logs in
  useEffect(() => {
    if (token) {
      refreshConversations()
      refreshFriends()
      refreshGroups()
      refreshFriendRequests()
    }
  }, [token, refreshConversations, refreshFriends, refreshGroups, refreshFriendRequests])

  return (
    <ChatContext.Provider
      value={{
        conversations,
        activeConversation,
        setActiveConversation: setConversationWithRef,
        messages,
        friends,
        friendRequests,
        groups,
        wsStatus,
        sendMessage,
        sendMediaMessage,
        refreshConversations,
        refreshFriends,
        refreshGroups,
        refreshFriendRequests,
        selectConversationByTarget,
      }}
    >
      {children}
    </ChatContext.Provider>
  )
}

export const useChat = () => {
  const context = useContext(ChatContext)
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider')
  }
  return context
}
