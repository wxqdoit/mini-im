import React, { useState, useEffect, useRef, useCallback } from 'react'
import { CallSession } from '../../types'
import { Phone, PhoneOff, Video, VideoOff, Mic, MicOff, User as UserIcon, Volume2, ShieldCheck } from 'lucide-react'

interface CallModalProps {
  call: CallSession
  localStream: MediaStream | null
  remoteStream: MediaStream | null
  onAccept: () => void
  onReject: () => void
  onHangup: () => void
  onToggleMic: () => boolean
  onToggleCam: () => boolean
  onRetryRealCamera?: () => Promise<boolean>
}

export const CallModal: React.FC<CallModalProps> = ({
  call,
  localStream,
  remoteStream,
  onAccept,
  onReject,
  onHangup,
  onToggleMic,
  onToggleCam,
  onRetryRealCamera,
}) => {
  const [isMuted, setIsMuted] = useState(false)
  const [isCamOff, setIsCamOff] = useState(false)
  const [callDuration, setCallDuration] = useState(0)
  const [autoplayBlocked, setAutoplayBlocked] = useState(false)

  const localVideoRef = useRef<HTMLVideoElement | null>(null)
  const remoteVideoRef = useRef<HTMLVideoElement | null>(null)
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null)

  // Explicitly bind and trigger play on HTML media elements
  const bindLocalVideo = useCallback((node: HTMLVideoElement | null) => {
    localVideoRef.current = node
    if (node && localStream) {
      if (node.srcObject !== localStream) {
        node.srcObject = localStream
      }
      node.play().catch((err) => {
        console.warn('[WebRTC] Local video play error:', err)
      })
    }
  }, [localStream])

  const bindRemoteVideo = useCallback((node: HTMLVideoElement | null) => {
    remoteVideoRef.current = node
    if (node && remoteStream) {
      if (node.srcObject !== remoteStream) {
        node.srcObject = remoteStream
      }
      node.play().catch((err) => {
        console.warn('[WebRTC] Remote video autoplay blocked:', err)
        setAutoplayBlocked(true)
      })
    }
  }, [remoteStream])

  const bindRemoteAudio = useCallback((node: HTMLAudioElement | null) => {
    remoteAudioRef.current = node
    if (node && remoteStream) {
      if (node.srcObject !== remoteStream) {
        node.srcObject = remoteStream
      }
      node.play().catch((err) => {
        console.warn('[WebRTC] Remote audio autoplay blocked:', err)
        setAutoplayBlocked(true)
      })
    }
  }, [remoteStream])

  // Sync streams whenever localStream or remoteStream change
  useEffect(() => {
    if (localVideoRef.current && localStream) {
      localVideoRef.current.srcObject = localStream
      localVideoRef.current.play().catch(() => {})
    }
  }, [localStream])

  useEffect(() => {
    if (remoteVideoRef.current && remoteStream) {
      remoteVideoRef.current.srcObject = remoteStream
      remoteVideoRef.current.play().catch(() => setAutoplayBlocked(true))
    }
    if (remoteAudioRef.current && remoteStream) {
      remoteAudioRef.current.srcObject = remoteStream
      remoteAudioRef.current.play().catch(() => setAutoplayBlocked(true))
    }
  }, [remoteStream])

  // Call timer when connected
  useEffect(() => {
    let timer: any = null
    if (call.status === 'connected') {
      timer = setInterval(() => {
        setCallDuration((prev) => prev + 1)
      }, 1000)
    } else {
      setCallDuration(0)
    }
    return () => {
      if (timer) clearInterval(timer)
    }
  }, [call.status])

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  const handleToggleMic = () => {
    const enabled = onToggleMic()
    setIsMuted(!enabled)
  }

  const handleToggleCam = () => {
    const enabled = onToggleCam()
    setIsCamOff(!enabled)
  }

  const handleUserUnblock = () => {
    setAutoplayBlocked(false)
    if (remoteVideoRef.current) remoteVideoRef.current.play().catch(() => {})
    if (remoteAudioRef.current) remoteAudioRef.current.play().catch(() => {})
    if (localVideoRef.current) localVideoRef.current.play().catch(() => {})
  }

  const targetName = call.target_user?.nickname || call.target_user?.username || '对方'
  const hasRemoteVideo = remoteStream && remoteStream.getVideoTracks().length > 0
  const hasRemoteAudio = remoteStream && remoteStream.getAudioTracks().length > 0

  return (
    <div onClick={handleUserUnblock} className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-md animate-in fade-in duration-200 cursor-default">
      {/* Hidden dedicated audio element to guarantee remote sound output */}
      <audio ref={bindRemoteAudio} autoPlay playsInline />

      <div className="relative w-full max-w-2xl overflow-hidden rounded-2xl bg-zinc-950 border border-zinc-800 shadow-2xl flex flex-col items-center">
        {/* Header Bar */}
        <div className="absolute top-4 left-6 z-20 flex items-center gap-3">
          <div className="flex h-3 w-3 relative">
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${call.status === 'connected' ? 'bg-emerald-400' : 'bg-amber-400'} opacity-75`}></span>
            <span className={`relative inline-flex rounded-full h-3 w-3 ${call.status === 'connected' ? 'bg-emerald-500' : 'bg-amber-500'}`}></span>
          </div>
          <span className="text-xs font-medium tracking-wide text-zinc-300 flex items-center gap-2">
            <span>{call.call_type === 'video' ? '视频通话' : '语音通话'}</span>
            <span>·</span>
            <span>
              {call.status === 'calling' ? '正在呼叫对方...' :
               call.status === 'ringing' ? '等待接听中...' :
               call.status === 'connected' ? `通话中 (${formatDuration(callDuration)})` : '已结束'}
            </span>
            {call.status === 'connected' && (
              <span className="hidden sm:inline-flex items-center gap-1 text-[11px] text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded-full border border-emerald-800/50">
                <ShieldCheck className="h-3 w-3" /> P2P 加密直连
              </span>
            )}
          </span>
        </div>

        {/* Browser Autoplay Blocked Notice */}
        {autoplayBlocked && (
          <div className="absolute top-12 z-30 px-4 py-2 bg-amber-500 text-black text-xs font-medium rounded-lg shadow-lg flex items-center gap-2 cursor-pointer animate-bounce" onClick={handleUserUnblock}>
            <Volume2 className="h-4 w-4" />
            <span>浏览器限制了自动播放，点击屏幕任意位置立即启用声音</span>
          </div>
        )}

        {/* Video / Audio Area */}
        <div className="relative w-full h-[440px] bg-zinc-900 flex items-center justify-center overflow-hidden">
          {call.call_type === 'video' ? (
            <>
              {/* Remote Video Stream (Main) - muted guarantees immediate video decode without browser autoplay blocking */}
              <video
                ref={bindRemoteVideo}
                autoPlay
                playsInline
                muted
                className={`w-full h-full object-cover transition-opacity duration-300 ${hasRemoteVideo ? 'opacity-100' : 'opacity-0'}`}
              />
              
              {/* Fallback / Waiting UI when remote video track hasn't arrived */}
              {!hasRemoteVideo && (
                <div className="absolute flex flex-col items-center gap-4 z-10">
                  <div className="h-28 w-28 rounded-full bg-zinc-800 border-4 border-zinc-700 flex items-center justify-center overflow-hidden shadow-2xl">
                    {call.target_user?.avatar ? (
                      <img src={call.target_user.avatar} alt={targetName} className="h-full w-full object-cover" />
                    ) : (
                      <UserIcon className="h-14 w-14 text-zinc-400" />
                    )}
                  </div>
                  <div className="text-center">
                    <h3 className="text-lg font-bold text-white mb-1">{targetName}</h3>
                    <p className="text-xs text-indigo-400 font-mono animate-pulse">
                      {call.status === 'connected' ? '正在同步高清视频轨道...' : '等待对方接受视频邀请...'}
                    </p>
                  </div>
                </div>
              )}

              {/* Local Video Stream (PiP Floating Window) */}
              <div className="absolute bottom-4 right-4 w-36 h-26 rounded-xl overflow-hidden border-2 border-zinc-700 shadow-2xl bg-black z-20">
                <video
                  ref={bindLocalVideo}
                  autoPlay
                  playsInline
                  muted
                  className={`w-full h-full object-cover ${isCamOff ? 'opacity-0' : 'opacity-100'}`}
                />
                {isCamOff && (
                  <div className="absolute inset-0 flex items-center justify-center bg-zinc-900 text-zinc-400 text-xs">
                    摄像头已关闭
                  </div>
                )}
                <div className="absolute bottom-1 left-2 right-2 flex items-center justify-between text-[10px] text-white/90">
                  <span className="bg-black/60 px-1 rounded">我</span>
                  {(localStream as any)?.__isVirtualFallback && (
                    <button
                      onClick={async (e) => {
                        e.stopPropagation()
                        const ok = await onRetryRealCamera?.()
                        if (!ok) alert('无法获取真实摄像头：请确认是否已授权浏览器访问摄像头，或关闭占用摄像头的其他窗口/软件。')
                      }}
                      className="bg-indigo-600/90 hover:bg-indigo-500 text-white px-1.5 py-0.5 rounded shadow text-[9px] font-medium transition-colors"
                      title="点击尝试切换为真实物理摄像头"
                    >
                      切换真摄像头
                    </button>
                  )}
                </div>
              </div>
            </>
          ) : (
            /* Audio Call Interface */
            <div className="flex flex-col items-center gap-5">
              <div className="relative">
                <div className={`absolute -inset-6 rounded-full bg-indigo-500/20 blur-xl ${call.status === 'connected' ? 'animate-pulse' : ''}`} />
                <div className="relative h-28 w-28 rounded-full border-4 border-indigo-500/40 bg-zinc-800 flex items-center justify-center overflow-hidden shadow-2xl">
                  {call.target_user?.avatar ? (
                    <img src={call.target_user.avatar} alt={targetName} className="h-full w-full object-cover" />
                  ) : (
                    <UserIcon className="h-14 w-14 text-zinc-300" />
                  )}
                </div>
              </div>
              <div className="text-center">
                <h3 className="text-xl font-bold text-white mb-1">{targetName}</h3>
                <p className="text-sm text-indigo-400 font-mono">
                  {call.status === 'connected' ? `通话中 ${formatDuration(callDuration)}` : 'Mini IM 高清实时音频通话'}
                </p>
                {hasRemoteAudio && (
                  <span className="inline-block mt-2 text-xs text-emerald-400 bg-emerald-950/60 px-2 py-0.5 rounded-full border border-emerald-800/40">
                    音频通道已建立
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Action Controls Bar */}
        <div className="w-full bg-zinc-950 p-6 flex items-center justify-center gap-6 border-t border-zinc-900">
          {call.direction === 'incoming' && call.status === 'ringing' ? (
            /* Incoming Call Controls */
            <div className="flex items-center gap-12">
              <button
                onClick={onReject}
                className="flex flex-col items-center gap-2 group transition-transform active:scale-95"
              >
                <div className="h-14 w-14 rounded-full bg-rose-600 hover:bg-rose-500 flex items-center justify-center text-white shadow-lg shadow-rose-900/40 transition-colors">
                  <PhoneOff className="h-6 w-6" />
                </div>
                <span className="text-xs font-medium text-zinc-400 group-hover:text-zinc-200">拒绝</span>
              </button>

              <button
                onClick={() => {
                  handleUserUnblock()
                  onAccept()
                }}
                className="flex flex-col items-center gap-2 group transition-transform active:scale-95"
              >
                <div className="h-14 w-14 rounded-full bg-emerald-600 hover:bg-emerald-500 flex items-center justify-center text-white shadow-lg shadow-emerald-900/40 transition-colors animate-bounce">
                  <Phone className="h-6 w-6" />
                </div>
                <span className="text-xs font-medium text-emerald-400 group-hover:text-emerald-300">接听</span>
              </button>
            </div>
          ) : (
            /* Active Call Controls */
            <div className="flex items-center gap-6">
              {/* Mic Toggle */}
              <button
                onClick={handleToggleMic}
                className={`h-12 w-12 rounded-full flex items-center justify-center transition-all ${
                  isMuted ? 'bg-amber-600/30 text-amber-400 border border-amber-500/50' : 'bg-zinc-800 hover:bg-zinc-700 text-white'
                }`}
                title={isMuted ? '取消静音' : '静音麦克风'}
              >
                {isMuted ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
              </button>

              {/* Camera Toggle (Video only) */}
              {call.call_type === 'video' && (
                <button
                  onClick={handleToggleCam}
                  className={`h-12 w-12 rounded-full flex items-center justify-center transition-all ${
                    isCamOff ? 'bg-amber-600/30 text-amber-400 border border-amber-500/50' : 'bg-zinc-800 hover:bg-zinc-700 text-white'
                  }`}
                  title={isCamOff ? '开启摄像头' : '关闭摄像头'}
                >
                  {isCamOff ? <VideoOff className="h-5 w-5" /> : <Video className="h-5 w-5" />}
                </button>
              )}

              {/* Hangup Button */}
              <button
                onClick={onHangup}
                className="h-12 px-6 rounded-full bg-rose-600 hover:bg-rose-500 flex items-center gap-2 text-white font-medium shadow-lg shadow-rose-900/40 transition-transform active:scale-95"
                title="结束通话"
              >
                <PhoneOff className="h-5 w-5" />
                <span className="text-sm">挂断</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
