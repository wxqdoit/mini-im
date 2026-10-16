export interface User {
  id: number
  username: string
  nickname: string
  avatar: string
  bio?: string
  status?: string
  is_online?: boolean
}

export interface Friend extends User {
  friendship_date?: string
}

export interface FriendRequest {
  id: number
  user_id: number
  username: string
  nickname: string
  avatar: string
  bio?: string
  message: string
  status: 'pending' | 'accepted' | 'rejected'
  created_at: string
}

export interface Group {
  id: number
  name: string
  avatar: string
  description?: string
  owner_id: number
  member_count?: number
  role?: 'owner' | 'admin' | 'member'
  my_role?: 'owner' | 'admin' | 'member'
  is_member?: boolean
  created_at?: string
}

export interface GroupMember {
  membership_id: number
  user_id: number
  username: string
  nickname: string
  avatar: string
  bio?: string
  role: 'owner' | 'admin' | 'member'
  joined_at: string
  is_online?: boolean
  status?: string
}

export interface Message {
  id: number
  conversation_type: 'direct' | 'group'
  sender_id: number
  recipient_id: number
  msg_type: 'text' | 'image' | 'file'
  content: string
  media_url?: string
  file_name?: string
  file_size?: number
  is_read?: boolean
  is_uploading?: boolean
  is_encrypted?: boolean
  iv?: string
  ephemeral_key?: string
  encrypted_key_bundle?: any
  created_at?: string
  sender?: {
    id: number
    username: string
    nickname: string
    avatar: string
  }
}

export interface Conversation {
  conversation_id: string
  type: 'direct' | 'group'
  target_id: number
  name: string
  avatar: string
  bio?: string
  description?: string
  is_online?: boolean
  status?: string
  last_message?: string
  last_message_id?: number
  last_time?: string | null
  unread_count: number
}
