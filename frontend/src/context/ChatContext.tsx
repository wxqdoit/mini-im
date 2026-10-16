import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { User, Friend, FriendRequest, Group, Message, Conversation } from '../types'
import { friendApi, groupApi, messageApi, uploadApi } from '../api/client'
import { useAuth } from './AuthContext'
import { playNotificationSound } from '../lib/utils'
import { CallSession } from "../types"
import { WebRTCManager } from "../lib/webrtc"
import { CallModal } from "../components/modals/CallModal"
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
  startCall: (callType: 'audio' | 'video', target: { id: number; name?: string; username?: string; avatar?: string }) => Promise<void>
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
  const [activeCall, setActiveCall] = useState<CallSession | null>(null)
  const [localStream, setLocalStream] = useState<MediaStream | null>(null)
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null)
  const webrtcManagerRef = useRef<WebRTCManager>(new WebRTCManager())
  const activeCallRef = useRef<CallSession | null>(null)

  useEffect(() => {
    activeCallRef.current = activeCall
  }, [activeCall])

  const sendSignaling = useCallback((type: string, data: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, ...data }))
    }
  }, [])

  useEffect(() => {
    const mgr = webrtcManagerRef.current
    mgr.setSignalingSender(sendSignaling)
    mgr.onLocalStream = (stream) => setLocalStream(stream)
    mgr.onRemoteStream = (stream) => setRemoteStream(stream)
    mgr.onCallEnded = () => {
      mgr.cleanup()
      setActiveCall(null)
      setLocalStream(null)
      setRemoteStream(null)
    }
  }, [sendSignaling])

  const startCall = useCallback(async (callType: 'audio' | 'video', target: { id: number; name?: string; username?: string; avatar?: string }) => {
    const callId = `call_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
    const session: CallSession = {
      call_id: callId,
      target_id: target.id,
      target_user: { id: target.id, nickname: target.name || target.username || "对方", avatar: target.avatar },
      call_type: callType,
      direction: "outgoing",
      status: "calling",
    }
    activeCallRef.current = session
    setActiveCall(session)
    try {
      await webrtcManagerRef.current.getLocalMedia(callType, userRef.current?.nickname || userRef.current?.username || "我")
      webrtcManagerRef.current.initPeerConnection(callId, target.id)
      sendSignaling("call_invite", {
        call_id: callId,
        recipient_id: target.id,
        call_type: callType,
      })
    } catch (err) {
      console.error("[WebRTC] Failed to start call:", err)
      alert("无法访问摄像头或麦克风设备，请检查浏览器权限")
      webrtcManagerRef.current.cleanup()
      setActiveCall(null)
      setLocalStream(null)
      setRemoteStream(null)
    }
  }, [sendSignaling])

  const acceptCall = useCallback(async () => {
    const call = activeCallRef.current
    if (!call) return
    const connectedSession: CallSession = { ...call, status: "connected" }
    activeCallRef.current = connectedSession
    setActiveCall(connectedSession)
    try {
      await webrtcManagerRef.current.getLocalMedia(call.call_type, userRef.current?.nickname || userRef.current?.username || "我")
      webrtcManagerRef.current.initPeerConnection(call.call_id, call.target_id)
      sendSignaling("call_accept", {
        call_id: call.call_id,
        caller_id: call.target_id,
      })
    } catch (err) {
      console.error("[WebRTC] Failed to accept call:", err)
      alert("无法访问媒体设备")
      webrtcManagerRef.current.cleanup()
      setActiveCall(null)
      setLocalStream(null)
      setRemoteStream(null)
    }
  }, [sendSignaling])

  const rejectCall = useCallback(() => {
    const call = activeCallRef.current
    if (call) {
      sendSignaling("call_reject", {
        call_id: call.call_id,
        caller_id: call.target_id,
        reason: "declined",
      })
    }
    webrtcManagerRef.current.cleanup()
    activeCallRef.current = null
    setActiveCall(null)
    setLocalStream(null)
    setRemoteStream(null)
  }, [sendSignaling])

  const hangupCall = useCallback(() => {
    const call = activeCallRef.current
    if (call) {
      sendSignaling("call_hangup", {
        call_id: call.call_id,
        target_id: call.target_id,
      })
    }
    webrtcManagerRef.current.cleanup()
    activeCallRef.current = null
    setActiveCall(null)
    setLocalStream(null)
    setRemoteStream(null)
  }, [sendSignaling])

  const toggleMic = useCallback(() => {
    return webrtcManagerRef.current.toggleAudio()
  }, [])

  const toggleCam = useCallback(() => {
    return webrtcManagerRef.current.toggleVideo()
  }, [])

  const retryRealCamera = useCallback(async () => {
    return await webrtcManagerRef.current.upgradeToRealCamera()
  }, [])

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
        if (newMsg.conversation_type === 'group') {
          // Group chats share symmetric key: all members (including sender) decrypt
          newMsg.content = await decryptGroupMessage(newMsg.recipient_id, newMsg)
        } else if (Number(newMsg.sender_id) !== Number(curUid)) {
          newMsg.content = await decryptDirectMessage(curUid, newMsg)
        } else {
          if (newMsg.iv) {
            try {
              const cached = localStorage.getItem(`mini_im_sent_txt_${newMsg.iv}`) ||
                             sessionStorage.getItem(`mini_im_sent_txt_${newMsg.iv}`)
              if (cached) newMsg.content = cached
            } catch (_) {}
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
              (Boolean(newMsg.iv) && Boolean(m.iv) && newMsg.iv === m.iv) ||
              m.content === newMsg.content ||
              (newMsg.media_url && (m.media_url === newMsg.media_url || m.media_url?.startsWith("blob:")))
            )
          )
          if (tempIdx !== -1) {
            const copy = [...prev]
            const preservedContent = (Number(newMsg.sender_id) === Number(currentUser?.id) && copy[tempIdx].content)
              ? copy[tempIdx].content
              : newMsg.content
            copy[tempIdx] = {
              ...newMsg,
              content: preservedContent || newMsg.content,
            }
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
    } else if (eventName === 'call_invite') {
      playNotificationSound()
      const incomingSession: CallSession = {
        call_id: data.call_id,
        target_id: data.caller_id,
        target_user: data.caller,
        call_type: data.call_type || "video",
        direction: "incoming",
        status: "ringing",
      }
      activeCallRef.current = incomingSession
      setActiveCall(incomingSession)
      sendSignaling("call_ringing", { call_id: data.call_id, caller_id: data.caller_id })
    } else if (eventName === 'call_ringing') {
      if (activeCallRef.current?.call_id === data.call_id) {
        activeCallRef.current = { ...activeCallRef.current, status: "ringing" }
        setActiveCall(prev => prev ? { ...prev, status: "ringing" } : null)
      }
    } else if (eventName === 'call_accept') {
      if (activeCallRef.current?.call_id === data.call_id) {
        activeCallRef.current = { ...activeCallRef.current, status: "connected" }
        setActiveCall(prev => prev ? { ...prev, status: "connected" } : null)
        const peerTargetId = data.recipient_id || activeCallRef.current?.target_id
        webrtcManagerRef.current.createOffer().then(offer => {
          sendSignaling("webrtc_offer", {
            call_id: data.call_id,
            target_id: peerTargetId,
            sdp: offer,
          })
        }).catch(err => console.error("[WebRTC] Error creating offer:", err))
      }
    } else if (eventName === 'call_reject') {
      alert(`对方已拒绝通话 (${data.reason || "已拒绝"})`)
      webrtcManagerRef.current.cleanup()
      activeCallRef.current = null
      setActiveCall(null)
      setLocalStream(null)
      setRemoteStream(null)
    } else if (eventName === 'call_hangup') {
      webrtcManagerRef.current.cleanup()
      activeCallRef.current = null
      setActiveCall(null)
      setLocalStream(null)
      setRemoteStream(null)
    } else if (eventName === 'call_failed') {
      alert(`通话失败: ${data.reason || "对方当前不在线"}`)
      webrtcManagerRef.current.cleanup()
      activeCallRef.current = null
      setActiveCall(null)
      setLocalStream(null)
      setRemoteStream(null)
    } else if (eventName === 'webrtc_offer') {
      if (activeCallRef.current?.call_id === data.call_id) {
        webrtcManagerRef.current.handleOffer(data.sdp).then(answer => {
          sendSignaling("webrtc_answer", {
            call_id: data.call_id,
            target_id: data.sender_id,
            sdp: answer,
          })
        }).catch(err => console.error("[WebRTC] Error handling offer:", err))
      }
    } else if (eventName === 'webrtc_answer') {
      if (activeCallRef.current?.call_id === data.call_id) {
        webrtcManagerRef.current.handleAnswer(data.sdp).catch(err =>
          console.error("[WebRTC] Error handling answer:", err)
        )
      }
    } else if (eventName === 'webrtc_ice_candidate') {
      if (activeCallRef.current?.call_id === data.call_id && data.candidate) {
        webrtcManagerRef.current.addIceCandidate(data.candidate).catch(err =>
          console.error("[WebRTC] Error adding ICE candidate:", err)
        )
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
          messageApi.getHistory(cur.type, cur.target_id).then(async res => {
            const rawList = res.data.messages || []
            const currentUid = userRef.current?.id || 0
            const decryptedList = await Promise.all(
              rawList.map(async (m: Message) => {
                if (m.is_encrypted && m.msg_type === 'text') {
                  if (cur.type === 'direct') {
                    const dec = await decryptDirectMessage(currentUid, m)
                    return { ...m, content: dec }
                  } else {
                    const dec = await decryptGroupMessage(cur.target_id, m)
                    return { ...m, content: dec }
                  }
                }
                return m
              })
            )
            setMessages(decryptedList)
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
        startCall,
      }}
    >
      {children}
      {activeCall && (
        <CallModal
          call={activeCall}
          localStream={localStream}
          remoteStream={remoteStream}
          onAccept={acceptCall}
          onReject={rejectCall}
          onHangup={hangupCall}
          onToggleMic={toggleMic}
          onToggleCam={toggleCam}
          onRetryRealCamera={retryRealCamera}
        />
      )}
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
