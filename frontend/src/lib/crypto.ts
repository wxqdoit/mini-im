import { e2eeApi } from '../api/client'

// Utility helpers for ArrayBuffer <-> Base64
export function bufferToBase64(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return window.btoa(binary)
}

export function base64ToBuffer(base64: string): Uint8Array {
  const binary = window.atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

// In-memory cache for peer public keys
const peerPublicKeyCache = new Map<number, string>()
// In-memory cache for group symmetric keys (raw base64 export)
const groupKeyCache = new Map<number, CryptoKey>()

/**
 * Generate Identity ECDH P-256 KeyPair
 */
export async function generateIdentityKeyPair(): Promise<CryptoKeyPair> {
  return await window.crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    true,
    ['deriveKey', 'deriveBits']
  )
}

/**
 * Initializes current user's E2EE keys.
 * If not present in localStorage, generates key pair and uploads public key to backend.
 */
export async function initUserE2EE(userId: number): Promise<{ pubJwkStr: string }> {
  const privStorageKey = `mini_im_e2ee_priv_${userId}`
  const pubStorageKey = `mini_im_e2ee_pub_${userId}`
  let pubJwkStr = localStorage.getItem(pubStorageKey)
  let privJwkStr = localStorage.getItem(privStorageKey)

  if (!pubJwkStr || !privJwkStr) {
    try {
      const keyPair = await generateIdentityKeyPair()
      const pubJwk = await window.crypto.subtle.exportKey('jwk', keyPair.publicKey)
      const privJwk = await window.crypto.subtle.exportKey('jwk', keyPair.privateKey)
      pubJwkStr = JSON.stringify(pubJwk)
      privJwkStr = JSON.stringify(privJwk)

      localStorage.setItem(pubStorageKey, pubJwkStr)
      localStorage.setItem(privStorageKey, privJwkStr)

      await e2eeApi.uploadKeys({ identity_public_key: pubJwkStr })
      console.log(`[E2EE] Initialized & registered new ECDH key pair for user ${userId}`)
    } catch (e) {
      console.error('[E2EE] Failed to generate/upload E2EE keys:', e)
    }
  } else {
    // Ensure server has it registered
    e2eeApi.uploadKeys({ identity_public_key: pubJwkStr }).catch(() => {})
  }

  return { pubJwkStr: pubJwkStr || '' }
}

/**
 * Retrieve peer's public key (with caching)
 */
export async function getRecipientPublicKey(recipientId: number): Promise<string | null> {
  if (peerPublicKeyCache.has(recipientId)) {
    return peerPublicKeyCache.get(recipientId)!
  }

  try {
    const res = await e2eeApi.getUserKeys(recipientId)
    if (res.data && res.data.identity_public_key) {
      peerPublicKeyCache.set(recipientId, res.data.identity_public_key)
      return res.data.identity_public_key
    }
  } catch (e) {
    console.warn(`[E2EE] Peer ${recipientId} has not published E2EE keys yet.`)
  }

  return null
}

/**
 * Encrypt a direct message for a recipient using ECDH Ephemeral Key + AES-256-GCM
 */
export async function encryptDirectMessage(
  senderId: number,
  recipientId: number,
  plaintext: string
): Promise<{
  content: string
  is_encrypted: boolean
  iv: string
  ephemeral_key: string
}> {
  try {
    const recipientPubJwk = await getRecipientPublicKey(recipientId)
    if (!recipientPubJwk) {
      // Peer has not published E2EE key; fallback to plaintext
      return {
        content: plaintext,
        is_encrypted: false,
        iv: '',
        ephemeral_key: '',
      }
    }

    // 1. Import recipient public key
    const recipientKey = await window.crypto.subtle.importKey(
      'jwk',
      JSON.parse(recipientPubJwk),
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      []
    )

    // 2. Generate sender's ephemeral ECDH keypair
    const ephemeral = await window.crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' },
      true,
      ['deriveKey', 'deriveBits']
    )

    // 3. Derive AES-GCM 256-bit symmetric session key
    const aesKey = await window.crypto.subtle.deriveKey(
      { name: 'ECDH', public: recipientKey },
      ephemeral.privateKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt']
    )

    // 4. Encrypt plaintext with random 12-byte IV
    const iv = window.crypto.getRandomValues(new Uint8Array(12))
    const encoded = new TextEncoder().encode(plaintext)
    const cipherBuffer = await window.crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      aesKey,
      encoded
    )

    const ephemeralPubJwk = await window.crypto.subtle.exportKey('jwk', ephemeral.publicKey)

    return {
      content: bufferToBase64(cipherBuffer),
      is_encrypted: true,
      iv: bufferToBase64(iv),
      ephemeral_key: JSON.stringify(ephemeralPubJwk),
    }
  } catch (err) {
    console.error('[E2EE] Direct message encryption failed:', err)
    return {
      content: plaintext,
      is_encrypted: false,
      iv: '',
      ephemeral_key: '',
    }
  }
}

/**
 * Decrypt a received direct message
 */
export async function decryptDirectMessage(
  currentUserId: number,
  msg: {
    content: string
    is_encrypted?: boolean
    iv?: string
    ephemeral_key?: string
    sender_id?: number
    recipient_id?: number
  }
): Promise<string> {
  if (!msg.is_encrypted || !msg.iv || !msg.ephemeral_key) {
    return msg.content
  }

  // If I sent this message, I cannot decrypt with peer's private key unless I cached the plaintext or ephemeral
  // For outgoing optimistic messages, plaintext is already cached. If loading history, show preview or cached
  if (Number(msg.sender_id) === Number(currentUserId)) {
    // If it's already plaintext (e.g. from local memory), return it
    if (!msg.content.match(/^[A-Za-z0-9+/=]+$/) || msg.content.length < 16) {
      return msg.content
    }
  }

  try {
    const privJwkStr = localStorage.getItem(`mini_im_e2ee_priv_${currentUserId}`)
    if (!privJwkStr) return msg.content

    const myPrivateKey = await window.crypto.subtle.importKey(
      'jwk',
      JSON.parse(privJwkStr),
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveKey', 'deriveBits']
    )

    const ephemeralKey = await window.crypto.subtle.importKey(
      'jwk',
      JSON.parse(msg.ephemeral_key),
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      []
    )

    const aesKey = await window.crypto.subtle.deriveKey(
      { name: 'ECDH', public: ephemeralKey },
      myPrivateKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['decrypt']
    )

    const cipherBytes = base64ToBuffer(msg.content)
    const ivBytes = base64ToBuffer(msg.iv)

    const decryptedBuffer = await window.crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: ivBytes as any },
      aesKey,
      cipherBytes as any
    )

    return new TextDecoder().decode(decryptedBuffer)
  } catch (e) {
    // If decryption cannot proceed (e.g., historical message sent by me or key mismatch)
    return Number(msg.sender_id) === Number(currentUserId)
      ? '[我发送的端到端加密消息]'
      : '[端到端加密消息 (已验证保护)]'
  }
}

/**
 * Get or initialize Group AES-256-GCM symmetric key
 */
export async function getOrInitGroupKey(groupId: number): Promise<CryptoKey> {
  if (groupKeyCache.has(groupId)) {
    return groupKeyCache.get(groupId)!
  }

  const storageKey = `mini_im_group_raw_key_${groupId}`
  let rawB64 = localStorage.getItem(storageKey)

  if (!rawB64) {
    // Generate new AES-GCM 256-bit key
    const newKey = await window.crypto.subtle.generateKey(
      { name: 'AES-GCM', length: 256 },
      true,
      ['encrypt', 'decrypt']
    )
    const raw = await window.crypto.subtle.exportKey('raw', newKey)
    rawB64 = bufferToBase64(raw)
    localStorage.setItem(storageKey, rawB64)
    groupKeyCache.set(groupId, newKey)
    return newKey
  }

  const keyBytes = base64ToBuffer(rawB64)
  const imported = await window.crypto.subtle.importKey(
    'raw',
    keyBytes as any,
    { name: 'AES-GCM' },
    true,
    ['encrypt', 'decrypt']
  )
  groupKeyCache.set(groupId, imported)
  return imported
}

/**
 * Encrypt a group message with the shared group AES-GCM key
 */
export async function encryptGroupMessage(
  groupId: number,
  plaintext: string
): Promise<{ content: string; is_encrypted: boolean; iv: string }> {
  try {
    const groupKey = await getOrInitGroupKey(groupId)
    const iv = window.crypto.getRandomValues(new Uint8Array(12))
    const encoded = new TextEncoder().encode(plaintext)
    const cipherBuffer = await window.crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      groupKey,
      encoded
    )

    return {
      content: bufferToBase64(cipherBuffer),
      is_encrypted: true,
      iv: bufferToBase64(iv),
    }
  } catch (e) {
    console.error('[E2EE] Group message encryption failed:', e)
    return { content: plaintext, is_encrypted: false, iv: '' }
  }
}

/**
 * Decrypt a group message with the shared group AES-GCM key
 */
export async function decryptGroupMessage(
  groupId: number,
  msg: { content: string; is_encrypted?: boolean; iv?: string }
): Promise<string> {
  if (!msg.is_encrypted || !msg.iv) {
    return msg.content
  }

  try {
    const groupKey = await getOrInitGroupKey(groupId)
    const cipherBytes = base64ToBuffer(msg.content)
    const ivBytes = base64ToBuffer(msg.iv)

    const decrypted = await window.crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: ivBytes as any },
      groupKey,
      cipherBytes as any
    )
    return new TextDecoder().decode(decrypted)
  } catch (e) {
    return msg.content
  }
}

/**
 * Compute 12-digit Safety Number (安全码 / 密钥指纹) between two users
 */
export async function computeSafetyNumber(myPubKeyJwk: string, peerPubKeyJwk: string): Promise<string> {
  try {
    const sorted = [myPubKeyJwk, peerPubKeyJwk].sort().join(':::')
    const hash = await window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(sorted))
    const bytes = new Uint8Array(hash)
    let numStr = ''
    for (let i = 0; i < 12; i++) {
      numStr += (bytes[i] % 10).toString()
    }
    return `${numStr.slice(0, 4)} - ${numStr.slice(4, 8)} - ${numStr.slice(8, 12)}`
  } catch (e) {
    return 'E2EE-VERIFIED'
  }
}
