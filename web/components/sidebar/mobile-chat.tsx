'use client'

import { useState, useEffect, useCallback } from 'react'
import { MessageSquare, X } from 'lucide-react'
import { AIChat } from './ai-chat'

export function MobileChatFAB() {
  const [open, setOpen] = useState(false)

  const closeModal = useCallback(() => setOpen(false), [])

  useEffect(() => {
    if (!open) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeModal()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, closeModal])

  return (
    <div className="lg:hidden">
      {/* FAB */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-50 w-14 h-14 rounded-full shadow-lg flex items-center justify-center text-white bg-gradient-brand"
        >
          <MessageSquare className="w-6 h-6" />
        </button>
      )}

      {/* Chat Modal */}
      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-50 bg-black/30" onClick={closeModal} />

          {/* Chat Panel */}
          <div
            role="dialog"
            aria-modal="true"
            className="fixed bottom-0 left-0 right-0 z-50 flex flex-col bg-white rounded-t-2xl shadow-2xl overflow-hidden"
            style={{ height: '55vh', maxHeight: '450px' }}
          >
            {/* Close bar */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 shrink-0">
              <span className="text-xs text-gray-400">AI Assistant</span>
              <button onClick={closeModal} className="p-1 rounded-full hover:bg-gray-100">
                <X className="w-4 h-4 text-gray-400" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden">
              <AIChat forceExpanded />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
