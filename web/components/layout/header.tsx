'use client'

import { useEffect, useState } from 'react'
import { formatDateTime } from '@/lib/utils'
import { Clock } from 'lucide-react'

export function Header() {
  const [lastUpdate, setLastUpdate] = useState<string>('')

  useEffect(() => {
    // Fetch last scan time from alerts
    const fetchLastUpdate = async () => {
      try {
        const res = await fetch('/api/alerts')
        const data = await res.json()
        if (data.timestamp) {
          setLastUpdate(formatDateTime(data.timestamp))
        }
      } catch (error) {
        console.error('Failed to fetch last update:', error)
      }
    }

    fetchLastUpdate()
    const interval = setInterval(fetchLastUpdate, 60000) // Update every minute

    return () => clearInterval(interval)
  }, [])

  return (
    <div className="flex h-16 items-center justify-between border-b bg-card px-6">
      <div className="flex items-center gap-4">
        <h2 className="text-lg font-semibold">Trading Dashboard</h2>
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Clock className="h-4 w-4" />
        <span>Last scan: {lastUpdate || 'Never'}</span>
      </div>
    </div>
  )
}
