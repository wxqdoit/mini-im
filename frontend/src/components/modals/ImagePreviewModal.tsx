import React from 'react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Download, X } from 'lucide-react'

interface ImagePreviewModalProps {
  url: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export const ImagePreviewModal: React.FC<ImagePreviewModalProps> = ({ url, open, onOpenChange }) => {
  if (!url) return null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl p-2 bg-transparent border-0 shadow-none flex flex-col items-center justify-center">
        <div className="relative max-h-[85vh] max-w-[90vw] overflow-hidden rounded-2xl bg-black/80 backdrop-blur-md p-2 flex flex-col items-center">
          <img
            src={url}
            alt="Preview"
            className="max-h-[75vh] max-w-[85vw] object-contain rounded-xl select-none"
          />
          <div className="mt-3 flex items-center gap-3">
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              download
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white text-xs backdrop-blur-sm transition"
            >
              <Download className="w-3.5 h-3.5" /> 下载原图
            </a>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
