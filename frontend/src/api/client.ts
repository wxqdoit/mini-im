import axios from 'axios'
import { User, Friend, FriendRequest, Group, GroupMember, Message, Conversation } from '../types'

export const API_BASE = '/api'

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Helper to generate 32-hex trace ID and 16-hex span ID (W3C standard)
function generateHex(len: number): string {
  const chars = '0123456789abcdef'
  let res = ''
  for (let i = 0; i < len; i++) {
    res += chars[Math.floor(Math.random() * 16)]
  }
  return res
}

// Request interceptor to attach JWT token and W3C Distributed Trace headers
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('mini_im_token')
  if (token && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const traceId = generateHex(32)
  const spanId = generateHex(16)
  config.headers['traceparent'] = `00-${traceId}-${spanId}-01`
  config.headers['X-Trace-Id'] = traceId
  return config
})

// Response interceptor to handle 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    return Promise.reject(error)
  }
)

export const authApi = {
  login: (data: { username: string; password: string }) =>
    api.post<{ message: string; token: string; user: User }>('/auth/login', data),
  
  register: (data: { username: string; password: string; nickname?: string; avatar?: string; bio?: string }) =>
    api.post<{ message: string; token: string; user: User }>('/auth/register', data),
  
  logout: (tokenOverride?: string) =>
    api.post<{ message: string }>(
      '/auth/logout',
      {},
      tokenOverride ? { headers: { Authorization: `Bearer ${tokenOverride}` } } : {}
    ),

  getMe: () => api.get<{ user: User }>('/auth/me'),
}

export const userApi = {
  updateProfile: (data: { nickname?: string; bio?: string; avatar?: string; status?: string }) =>
    api.put<{ message: string; user: User }>('/users/profile', data),
  
  searchUsers: (query: string) =>
    api.get<{ users: (User & { is_friend: boolean; request_sent: boolean })[] }>(`/users/search?q=${encodeURIComponent(query)}`),

  registerDeviceToken: (platform: string, device_token: string) =>
    api.post<{ message: string }>('/users/device-token', { platform, device_token }),

  unregisterDeviceToken: (device_token?: string) =>
    api.delete<{ message: string }>('/users/device-token', { data: { device_token } }),

  getPushNotifications: (limit = 20) =>
    api.get<{ notifications: any[] }>(`/users/push-notifications?limit=${limit}`),
}

export const friendApi = {
  getFriends: () => api.get<{ friends: Friend[] }>('/friends'),
  
  sendRequest: (receiver_id: number, message?: string) =>
    api.post<{ message: string; request_id: number }>('/friends/request', { receiver_id, message }),
  
  getRequests: () =>
    api.get<{ received: FriendRequest[]; sent: FriendRequest[] }>('/friends/requests'),
  
  respondRequest: (requestId: number, action: 'accept' | 'reject') =>
    api.post<{ message: string }>(`/friends/requests/${requestId}/respond`, { action }),
  
  deleteFriend: (friendId: number) =>
    api.delete<{ message: string }>(`/friends/${friendId}`),
}

export const groupApi = {
  getMyGroups: () => api.get<{ groups: Group[] }>('/groups'),
  
  searchGroups: (query: string) =>
    api.get<{ groups: Group[] }>(`/groups/search?q=${encodeURIComponent(query)}`),
  
  createGroup: (data: { name: string; description?: string; avatar?: string }) =>
    api.post<{ message: string; group: Group }>('/groups', data),
  
  getGroupDetail: (groupId: number) =>
    api.get<{ group: Group }>(`/groups/${groupId}`),
  
  getMembers: (groupId: number) =>
    api.get<{ members: GroupMember[] }>(`/groups/${groupId}/members`),
  
  joinGroup: (groupId: number) =>
    api.post<{ message: string }>(`/groups/${groupId}/join`),
  
  inviteMembers: (groupId: number, user_ids: number[]) =>
    api.post<{ message: string; added_user_ids: number[] }>(`/groups/${groupId}/invite`, { user_ids }),
  
  leaveGroup: (groupId: number) =>
    api.post<{ message: string }>(`/groups/${groupId}/leave`),
  
  disbandGroup: (groupId: number) =>
    api.delete<{ message: string }>(`/groups/${groupId}`),
}

export const messageApi = {
  sendMessage: (data: {
    conversation_type: 'direct' | 'group'
    recipient_id: number
    msg_type?: 'text' | 'image' | 'file'
    content?: string
    media_url?: string
    file_name?: string
    file_size?: number
    is_encrypted?: boolean
    iv?: string
    ephemeral_key?: string
    encrypted_key_bundle?: any
  }) => api.post<{ status: string; message: string }>('/messages/send', data),

  getHistory: (type: 'direct' | 'group', targetId: number, limit = 50, beforeId?: number) => {
    let url = `/messages/history?type=${type}&target_id=${targetId}&limit=${limit}`
    if (beforeId) url += `&before_id=${beforeId}`
    return api.get<{ messages: Message[] }>(url)
  },

  markRead: (senderId: number) =>
    api.post<{ message: string }>('/messages/read', { sender_id: senderId }),

  getConversations: () =>
    api.get<{ conversations: Conversation[] }>('/messages/conversations'),
}

export const e2eeApi = {
  uploadKeys: (data: { identity_public_key: string; signed_prekey?: string; prekey_signature?: string }) =>
    api.post<{ message: string }>('/e2ee/keys', data),

  getUserKeys: (userId: number) =>
    api.get<{ user_id: number; identity_public_key: string; signed_prekey?: string; prekey_signature?: string }>(`/e2ee/keys/${userId}`),

  getBatchKeys: (userIds: number[]) =>
    api.post<{ keys: Record<string, { identity_public_key: string }> }>('/e2ee/keys/batch', { user_ids: userIds }),

  getGroupKeys: (groupId: number) =>
    api.get<{ has_key: boolean; key_version?: number; user_key_data?: any; all_keys?: any }>(`/e2ee/group-keys/${groupId}`),

  setGroupKeys: (groupId: number, data: { encrypted_keys: Record<string, any>; key_version?: number }) =>
    api.post<{ message: string; key_version: number }>(`/e2ee/group-keys/${groupId}`, data),
}

export const uploadApi = {
  uploadFile: (file: File, folder: 'chat' | 'avatars' = 'chat') => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('folder', folder)
    return api.post<{
      message: string
      url: string
      proxy_url: string
      file_name: string
      file_size: number
      content_type: string
    }>('/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
}
