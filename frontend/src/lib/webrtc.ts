/**
 * WebRTC Audio & Video Calling Manager (Production Hardened)
 * - Multi-STUN server failover (supporting China Domestic + Cloudflare + Google STUN)
 * - ICE candidate queue buffering (eliminates premature candidate drop before remoteDescription is ready)
 * - Track reference renewal (ensures React re-renders on both audio and video track arrival)
 * - Virtual Canvas video fallback (guarantees camera stream even if hardware camera is busy in multi-tab test)
 */

const DEFAULT_ICE_SERVERS: RTCIceServer[] = [
  { urls: 'stun:stun.chat.bilibili.com:3478' },
  { urls: 'stun:stun.qq.com:3478' },
  { urls: 'stun:stun.miwifi.com:3478' },
  { urls: 'stun:stun.cloudflare.com:3478' },
  { urls: 'stun:stun.l.google.com:19302' },
]

function createFallbackVideoStream(label: string = 'User Video'): MediaStream {
  const canvas = document.createElement('canvas')
  canvas.width = 640
  canvas.height = 480
  const ctx = canvas.getContext('2d')
  if (ctx) {
    let step = 0
    const render = () => {
      step += 0.03
      // Dynamic animated gradient background
      const grad = ctx.createLinearGradient(0, 0, canvas.width, canvas.height)
      grad.addColorStop(0, `hsl(${(step * 20) % 360}, 50%, 15%)`)
      grad.addColorStop(1, `hsl(${((step * 20) + 60) % 360}, 50%, 25%)`)
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      // Pulsating central avatar
      const radius = 60 + Math.sin(step * 3) * 5
      ctx.fillStyle = '#6366f1'
      ctx.beginPath()
      ctx.arc(320, 200, radius, 0, Math.PI * 2)
      ctx.fill()

      // Avatar border
      ctx.strokeStyle = '#a5b4fc'
      ctx.lineWidth = 4
      ctx.stroke()

      // Central initial
      ctx.fillStyle = '#ffffff'
      ctx.font = 'bold 36px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(label.slice(0, 1).toUpperCase() || 'U', 320, 200)

      // Subtitle
      ctx.font = 'bold 20px sans-serif'
      ctx.fillStyle = '#f8fafc'
      ctx.fillText(label, 320, 300)

      ctx.font = '14px sans-serif'
      ctx.fillStyle = '#94a3b8'
      ctx.fillText('多开测试模拟流 (双端真实设备通话将显示真实摄像头)', 320, 335)

      requestAnimationFrame(render)
    }
    render()
  }
  return canvas.captureStream(25)
}

function createFallbackAudioStream(): MediaStream {
  try {
    const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)()
    const osc = audioCtx.createOscillator()
    const dst = audioCtx.createMediaStreamDestination()
    const gain = audioCtx.createGain()
    gain.gain.value = 0.001 // subtle carrier to ensure audio track exists
    osc.connect(gain)
    gain.connect(dst)
    osc.start()
    return dst.stream
  } catch (e) {
    return new MediaStream()
  }
}

export class WebRTCManager {
  private pc: RTCPeerConnection | null = null
  private localStream: MediaStream | null = null
  private remoteStream: MediaStream | null = null
  private sendSignalingCallback: ((type: string, data: any) => void) | null = null
  private pendingCandidates: RTCIceCandidateInit[] = []

  public onRemoteStream?: (stream: MediaStream) => void
  public onLocalStream?: (stream: MediaStream) => void
  public onCallEnded?: () => void
  public onError?: (error: Error) => void

  constructor(sendSignaling?: (type: string, data: any) => void) {
    if (sendSignaling) {
      this.sendSignalingCallback = sendSignaling
    }
  }

  public setSignalingSender(callback: (type: string, data: any) => void) {
    this.sendSignalingCallback = callback
  }

  /**
   * Acquire local camera & microphone streams with high compatibility & fallback
   */
  public async getLocalMedia(callType: 'audio' | 'video' = 'video', username: string = '我'): Promise<MediaStream> {
    this.localStream = null
    let audioTrack: MediaStreamTrack | null = null
    let videoTrack: MediaStreamTrack | null = null
    let isVirtualVideo = false

    const hasMediaDevices = typeof navigator !== 'undefined' && !!navigator.mediaDevices && !!navigator.mediaDevices.getUserMedia

    if (hasMediaDevices) {
      if (callType === 'video') {
        // Priority 1: Unified audio + video request (standard browser prompt, zero race conditions)
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
            video: {
              width: { ideal: 1280, max: 1920 },
              height: { ideal: 720, max: 1080 },
            },
          })
          audioTrack = stream.getAudioTracks()[0] || null
          videoTrack = stream.getVideoTracks()[0] || null
          console.log('[WebRTC] Successfully acquired physical camera & mic via unified request')
        } catch (unifiedErr: any) {
          console.warn('[WebRTC] Unified getUserMedia failed, attempting unconstrained/individual requests:', unifiedErr)

          // Priority 2: Simple unconstrained video request (handles desktop webcams where resolutions or facingMode are incompatible)
          try {
            const vStream = await navigator.mediaDevices.getUserMedia({ video: true })
            videoTrack = vStream.getVideoTracks()[0] || null
            console.log('[WebRTC] Acquired real camera via unconstrained video query')
          } catch (vErr) {
            console.warn('[WebRTC] Real camera unavailable (device busy in multi-tab test or permission not granted):', vErr)
          }

          // Try microphone separately
          try {
            const aStream = await navigator.mediaDevices.getUserMedia({
              audio: { echoCancellation: true, noiseSuppression: true },
            })
            audioTrack = aStream.getAudioTracks()[0] || null
          } catch (aErr) {
            console.warn('[WebRTC] Microphone unavailable:', aErr)
          }
        }
      } else {
        // Audio call only
        try {
          const aStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true },
          })
          audioTrack = aStream.getAudioTracks()[0] || null
        } catch (aErr) {
          console.warn('[WebRTC] Microphone unavailable:', aErr)
        }
      }
    }

    // Audio fallback if microphone is blocked or absent
    if (!audioTrack) {
      console.info('[WebRTC] Using synthetic audio carrier')
      const mockAudio = createFallbackAudioStream()
      audioTrack = mockAudio.getAudioTracks()[0] || null
    }

    // Video fallback ONLY if physical camera is busy (e.g. multi-tab testing on same machine) or not permitted
    if (callType === 'video' && !videoTrack) {
      console.info('[WebRTC] Physical camera busy or blocked; deploying virtual test stream to prevent call interruption')
      const canvasStream = createFallbackVideoStream(username)
      videoTrack = canvasStream.getVideoTracks()[0] || null
      isVirtualVideo = true
    }

    const combinedTracks: MediaStreamTrack[] = []
    if (audioTrack) combinedTracks.push(audioTrack)
    if (videoTrack) combinedTracks.push(videoTrack)

    this.localStream = new MediaStream(combinedTracks)
    if (isVirtualVideo) {
      (this.localStream as any).__isVirtualFallback = true
    }

    console.log('[WebRTC] Local media stream ready. isVirtualFallback:', isVirtualVideo, 'Tracks:', combinedTracks.map(t => `${t.kind}:${t.readyState}`).join(', '))

    if (this.onLocalStream) {
      const fresh = new MediaStream(this.localStream.getTracks())
      if (isVirtualVideo) (fresh as any).__isVirtualFallback = true
      this.onLocalStream(fresh)
    }
    return this.localStream
  }

  /**
   * Attempt to upgrade from virtual fallback to real physical camera on user request
   */
  public async upgradeToRealCamera(): Promise<boolean> {
    if (!navigator.mediaDevices?.getUserMedia) return false
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      })
      const newVideoTrack = stream.getVideoTracks()[0]
      if (!newVideoTrack) return false

      // 1. Replace track in RTCPeerConnection sender
      if (this.pc) {
        const senders = this.pc.getSenders()
        const videoSender = senders.find(s => s.track && s.track.kind === 'video')
        if (videoSender) {
          await videoSender.replaceTrack(newVideoTrack)
        }
      }

      // 2. Replace track in localStream
      if (this.localStream) {
        const oldTrack = this.localStream.getVideoTracks()[0]
        if (oldTrack) {
          oldTrack.stop()
          this.localStream.removeTrack(oldTrack)
        }
        this.localStream.addTrack(newVideoTrack)
        delete (this.localStream as any).__isVirtualFallback
      }

      // 3. Notify UI
      if (this.onLocalStream && this.localStream) {
        const fresh = new MediaStream(this.localStream.getTracks())
        this.onLocalStream(fresh)
      }
      return true
    } catch (err) {
      console.warn('[WebRTC] Failed to upgrade to real camera:', err)
      return false
    }
  }

  /**
   * Initialize PeerConnection and bind event handlers
   */
  public initPeerConnection(callId: string, targetId: number): RTCPeerConnection {
    this.cleanupPeerConnection()
    this.pendingCandidates = []

    const config: RTCConfiguration = {
      iceServers: DEFAULT_ICE_SERVERS,
      iceCandidatePoolSize: 10,
    }

    this.pc = new RTCPeerConnection(config)
    this.remoteStream = new MediaStream()

    // 1. Add local media tracks to PeerConnection
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => {
        if (this.pc && this.localStream) {
          console.log('[WebRTC] Adding local track to PC:', track.kind)
          this.pc.addTrack(track, this.localStream)
        }
      })
    }

    // 2. Handle remote incoming tracks
    this.pc.ontrack = (event) => {
      console.log('[WebRTC] ontrack received remote track:', event.track.kind, event.track.id)
      
      if (!this.remoteStream) {
        this.remoteStream = new MediaStream()
      }

      // Add to our internal remote stream
      if (event.streams && event.streams[0]) {
        event.streams[0].getTracks().forEach((t) => {
          if (!this.remoteStream!.getTracks().some((cur) => cur.id === t.id)) {
            this.remoteStream!.addTrack(t)
          }
        })
      } else {
        if (!this.remoteStream.getTracks().some((cur) => cur.id === event.track.id)) {
          this.remoteStream.addTrack(event.track)
        }
      }

      // Re-emit with a brand new MediaStream reference so React state reliably re-renders!
      if (this.onRemoteStream) {
        const freshStream = new MediaStream(this.remoteStream.getTracks())
        console.log('[WebRTC] Emitting fresh remoteStream with tracks:', freshStream.getTracks().map(t => t.kind).join(','))
        this.onRemoteStream(freshStream)
      }
    }

    // 3. ICE Candidate gathering
    this.pc.onicecandidate = (event) => {
      if (event.candidate && this.sendSignalingCallback) {
        const payload = event.candidate.toJSON ? event.candidate.toJSON() : {
          candidate: event.candidate.candidate,
          sdpMid: event.candidate.sdpMid,
          sdpMLineIndex: event.candidate.sdpMLineIndex,
        }
        this.sendSignalingCallback('webrtc_ice_candidate', {
          call_id: callId,
          target_id: targetId,
          candidate: payload,
        })
      }
    }

    // 4. Connection & ICE state monitoring
    this.pc.oniceconnectionstatechange = () => {
      console.log('[WebRTC] ICE Connection State:', this.pc?.iceConnectionState)
      if (this.pc?.iceConnectionState === 'connected' || this.pc?.iceConnectionState === 'completed') {
        console.log('[WebRTC] ICE P2P Connection ESTABLISHED!')
      }
    }

    this.pc.onconnectionstatechange = () => {
      console.log('[WebRTC] PeerConnection State:', this.pc?.connectionState)
      if (this.pc?.connectionState === 'disconnected' || this.pc?.connectionState === 'failed') {
        if (this.onCallEnded) this.onCallEnded()
      }
    }

    return this.pc
  }

  /**
   * Create SDP Offer
   */
  public async createOffer(): Promise<RTCSessionDescriptionInit> {
    if (!this.pc) throw new Error('PeerConnection not initialized')
    const offer = await this.pc.createOffer({
      offerToReceiveAudio: true,
      offerToReceiveVideo: true,
    })
    await this.pc.setLocalDescription(offer)
    return offer
  }

  /**
   * Handle incoming SDP Offer and generate SDP Answer
   */
  public async handleOffer(offer: RTCSessionDescriptionInit): Promise<RTCSessionDescriptionInit> {
    if (!this.pc) throw new Error('PeerConnection not initialized')
    await this.pc.setRemoteDescription(new RTCSessionDescription(offer))
    await this.flushPendingCandidates()
    const answer = await this.pc.createAnswer()
    await this.pc.setLocalDescription(answer)
    return answer
  }

  /**
   * Handle incoming SDP Answer
   */
  public async handleAnswer(answer: RTCSessionDescriptionInit): Promise<void> {
    if (!this.pc) throw new Error('PeerConnection not initialized')
    await this.pc.setRemoteDescription(new RTCSessionDescription(answer))
    await this.flushPendingCandidates()
  }

  /**
   * Add incoming ICE Candidate with queue buffering
   */
  public async addIceCandidate(candidate: RTCIceCandidateInit): Promise<void> {
    if (!this.pc || !this.pc.remoteDescription || !this.pc.remoteDescription.type) {
      console.log('[WebRTC] Buffering ICE candidate until remote description is set')
      this.pendingCandidates.push(candidate)
      return
    }
    try {
      await this.pc.addIceCandidate(new RTCIceCandidate(candidate))
    } catch (err) {
      console.warn('[WebRTC] Error adding ICE candidate:', err)
    }
  }

  /**
   * Flush all buffered early ICE candidates
   */
  private async flushPendingCandidates(): Promise<void> {
    if (!this.pc || !this.pc.remoteDescription) return
    if (this.pendingCandidates.length > 0) {
      console.log(`[WebRTC] Flushing ${this.pendingCandidates.length} buffered ICE candidates`)
      while (this.pendingCandidates.length > 0) {
        const cand = this.pendingCandidates.shift()
        if (cand) {
          try {
            await this.pc.addIceCandidate(new RTCIceCandidate(cand))
          } catch (err) {
            console.warn('[WebRTC] Error flushing candidate:', err)
          }
        }
      }
    }
  }

  /**
   * Toggle microphone mute/unmute
   */
  public toggleAudio(): boolean {
    if (!this.localStream) return false
    const audioTrack = this.localStream.getAudioTracks()[0]
    if (audioTrack) {
      audioTrack.enabled = !audioTrack.enabled
      return audioTrack.enabled
    }
    return false
  }

  /**
   * Toggle camera enable/disable
   */
  public toggleVideo(): boolean {
    if (!this.localStream) return false
    const videoTrack = this.localStream.getVideoTracks()[0]
    if (videoTrack) {
      videoTrack.enabled = !videoTrack.enabled
      return videoTrack.enabled
    }
    return false
  }

  /**
   * Full teardown of media devices & peer connection
   */
  public cleanup(): void {
    if (this.localStream) {
      this.localStream.getTracks().forEach((track) => track.stop())
      this.localStream = null
    }
    this.cleanupPeerConnection()
  }

  private cleanupPeerConnection(): void {
    if (this.pc) {
      this.pc.onicecandidate = null
      this.pc.ontrack = null
      this.pc.onconnectionstatechange = null
      this.pc.oniceconnectionstatechange = null
      this.pc.close()
      this.pc = null
    }
    this.remoteStream = null
    this.pendingCandidates = []
  }
}
