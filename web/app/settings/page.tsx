'use client'

import { useEffect, useState } from 'react'
import { Config } from '@/lib/api'
import { Save } from 'lucide-react'
import { toast } from 'sonner'

export default function SettingsPage() {
  const [config, setConfig] = useState<Config | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await fetch('/api/config')
        const data = await res.json()
        setConfig(data)
      } catch (error) {
        console.error('Failed to fetch config:', error)
        toast.error('Failed to load configuration')
      } finally {
        setLoading(false)
      }
    }

    fetchConfig()
  }, [])

  const saveConfig = async () => {
    if (!config) return
    
    setSaving(true)
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })

      if (res.ok) {
        toast.success('Configuration saved successfully!')
      } else {
        toast.error('Failed to save configuration')
      }
    } catch (error) {
      console.error('Failed to save config:', error)
      toast.error('Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  const updateConfig = (path: string[], value: unknown) => {
    setConfig(prev => {
      if (!prev) return prev
      const newConfig = JSON.parse(JSON.stringify(prev)); // deep clone
      let current: Record<string, unknown> = newConfig;
      for (let i = 0; i < path.length - 1; i++) {
        current = current[path[i]] as Record<string, unknown>;
      }
      current[path[path.length - 1]] = value;
      return newConfig;
    });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-200px)]">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-brand-purple border-t-transparent"></div>
      </div>
    )
  }

  if (!config) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="bg-white rounded-lg border border-border p-12 text-center">
          <p className="text-muted-foreground">Failed to load configuration</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold mb-2">Learn & Settings</h1>
          <p className="text-muted-foreground">Configure your trading system</p>
        </div>
        <button
          onClick={saveConfig}
          disabled={saving}
          className="flex items-center gap-2 px-6 py-3 bg-gradient-brand text-white font-medium rounded-lg hover:opacity-90 transition-opacity"
        >
          <Save className="w-5 h-5" />
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>

      <div className="space-y-6">
        <div className="bg-white rounded-lg border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">Strategy Parameters</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="block text-sm font-medium mb-2">Min DTE</label>
              <input
                type="number"
                value={config.strategy.min_dte}
                onChange={(e) => updateConfig(['strategy', 'min_dte'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Max DTE</label>
              <input
                type="number"
                value={config.strategy.max_dte}
                onChange={(e) => updateConfig(['strategy', 'max_dte'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Min Delta</label>
              <input
                type="number"
                step="0.01"
                value={config.strategy.min_delta}
                onChange={(e) => updateConfig(['strategy', 'min_delta'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Max Delta</label>
              <input
                type="number"
                step="0.01"
                value={config.strategy.max_delta}
                onChange={(e) => updateConfig(['strategy', 'max_delta'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-border p-6">
          <h2 className="text-xl font-semibold mb-4">Risk Management</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="block text-sm font-medium mb-2">Account Size ($)</label>
              <input
                type="number"
                value={config.risk.account_size}
                onChange={(e) => updateConfig(['risk', 'account_size'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Max Risk Per Trade (%)</label>
              <input
                type="number"
                step="0.1"
                value={config.risk.max_risk_per_trade}
                onChange={(e) => updateConfig(['risk', 'max_risk_per_trade'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Profit Target (%)</label>
              <input
                type="number"
                value={config.risk.profit_target}
                onChange={(e) => updateConfig(['risk', 'profit_target'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Max Positions</label>
              <input
                type="number"
                value={config.risk.max_positions}
                onChange={(e) => updateConfig(['risk', 'max_positions'], Number(e.target.value))}
                className="w-full px-4 py-2 border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-purple"
              />
            </div>
          </div>
        </div>

        <div className="bg-gradient-brand rounded-lg p-6 text-white">
          <h2 className="text-xl font-semibold mb-2">📚 Learning Resources</h2>
          <p className="mb-4 opacity-90">
            Unlock premium educational content, video tutorials, and live trading sessions.
          </p>
          <a href="https://pilotai.com" target="_blank" rel="noopener noreferrer" className="inline-block px-6 py-2 bg-white text-brand-purple font-medium rounded-lg hover:bg-white/90 transition-colors">
            Learn More at PilotAI →
          </a>
        </div>
      </div>
    </div>
  )
}
