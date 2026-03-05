'use client'

import { useEffect, useState } from 'react'
import axios from 'axios'
import { Activity, Download, AlertCircle, CheckCircle, Clock, XCircle, List, BarChart2, Plus, Settings } from 'lucide-react'
import StatsOverview from '@/components/StatsOverview'
import QueueList from '@/components/QueueList'
import TimelineChart from '@/components/TimelineChart'
import ManualTaskForm from '@/components/ManualTaskForm'
import ScanSettings from '@/components/ScanSettings'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api'

export default function Home() {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [activeMenu, setActiveMenu] = useState<'queue' | 'stats'>('queue')
  const [activeTab, setActiveTab] = useState<'all' | 'pending' | 'downloading' | 'completed' | 'failed'>('all')
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)

  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/stats/overview`)
      setStats(response.data)
      setLoading(false)
    } catch (error) {
      console.error('Failed to fetch stats:', error)
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStats()
    const interval = setInterval(fetchStats, 10000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="min-h-screen bg-canvas flex items-center justify-center">
        <div className="text-center animate-fade-in">
          <div className="w-10 h-10 mx-auto mb-4 rounded-xl bg-accent/10 flex items-center justify-center">
            <Activity className="w-5 h-5 text-accent animate-pulse" />
          </div>
          <div className="space-y-2">
            <div className="h-3 w-32 skeleton mx-auto" />
            <div className="h-2 w-20 skeleton mx-auto" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <main id="main-content" className="min-h-screen bg-canvas">
      <div className="max-w-[1360px] mx-auto px-5 sm:px-8 lg:px-10 py-8 pb-16">
        {/* Header */}
        <header className="mb-10 flex justify-between items-start">
          <div>
            <h1 className="text-2xl sm:text-3xl font-semibold text-ink tracking-tight text-balance flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center flex-shrink-0">
                <Activity className="w-5 h-5 text-accent" />
              </div>
              HuggingFace Downloader
            </h1>
            <p className="mt-2 text-ink-secondary text-sm ml-12">Real-time monitoring of download queue and datasets</p>
          </div>
          <button
            onClick={() => setIsSettingsOpen(true)}
            className="btn flex items-center gap-2 px-3.5 py-2 bg-surface text-ink-secondary rounded-xl hover:bg-surface-sunken hover:text-ink shadow-soft text-sm font-medium"
          >
            <Settings className="w-4 h-4" />
            <span className="hidden sm:inline">Scan settings</span>
          </button>
        </header>

        {/* Scan Settings Modal */}
        <ScanSettings isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />

        {/* Main Menu Navigation */}
        <nav className="mb-8" aria-label="Main navigation">
          <div className="inline-flex items-center gap-1 p-1 bg-surface-sunken rounded-xl">
            <button
              onClick={() => setActiveMenu('queue')}
              className={`
                btn flex items-center gap-2 py-2 px-4 rounded-lg text-sm font-medium
                ${activeMenu === 'queue'
                  ? 'bg-surface text-ink shadow-soft'
                  : 'text-ink-secondary hover:text-ink'
                }
              `}
            >
              <List className="w-4 h-4" />
              Queue tasks
            </button>
            <button
              onClick={() => setActiveMenu('stats')}
              className={`
                btn flex items-center gap-2 py-2 px-4 rounded-lg text-sm font-medium
                ${activeMenu === 'stats'
                  ? 'bg-surface text-ink shadow-soft'
                  : 'text-ink-secondary hover:text-ink'
                }
              `}
            >
              <BarChart2 className="w-4 h-4" />
              Statistics
            </button>
          </div>
        </nav>

        {/* Content */}
        {activeMenu === 'queue' ? (
          <section className="space-y-6 animate-fade-in">
            {/* Manual Task Form */}
            <ManualTaskForm 
              isOpen={isModalOpen} 
              onClose={() => setIsModalOpen(false)} 
              onTaskAdded={fetchStats} 
            />

            {/* Queue Tabs & List */}
            <div>
              <div className="mb-5 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4">
                <nav className="flex items-center gap-1 overflow-x-auto pb-1" aria-label="Task filters">
                  {[
                    { key: 'all', label: 'All', icon: Activity },
                    { key: 'pending', label: 'Pending', icon: Clock },
                    { key: 'downloading', label: 'Downloading', icon: Download },
                    { key: 'completed', label: 'Completed', icon: CheckCircle },
                    { key: 'failed', label: 'Failed', icon: XCircle },
                  ].map((tab) => {
                    const Icon = tab.icon
                    const count = tab.key === 'all' 
                      ? Object.values(stats?.status_counts || {}).reduce((a: any, b: any) => a + b, 0)
                      : stats?.status_counts?.[tab.key] || 0
                    
                    return (
                      <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key as any)}
                        className={`
                          btn flex items-center gap-1.5 py-1.5 px-3 rounded-lg text-sm whitespace-nowrap
                          ${activeTab === tab.key
                            ? 'bg-accent text-white font-medium shadow-soft'
                            : 'text-ink-secondary hover:text-ink hover:bg-surface-sunken font-normal'
                          }
                        `}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        {tab.label}
                        <span className={`
                          tabular-nums text-xs font-mono px-1.5 py-0.5 rounded-md ml-0.5
                          ${activeTab === tab.key ? 'bg-white/20 text-white' : 'bg-surface-sunken text-ink-tertiary'}
                        `}>
                          {count}
                        </span>
                      </button>
                    )
                  })}
                </nav>
                <button
                  onClick={() => setIsModalOpen(true)}
                  className="btn flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-xl hover:bg-accent-hover shadow-soft text-sm font-medium flex-shrink-0"
                >
                  <Plus className="w-4 h-4" />
                  New task
                </button>
              </div>

              <QueueList status={activeTab === 'all' ? undefined : activeTab} />
            </div>
          </section>
        ) : (
          <section className="space-y-8 animate-fade-in">
            <StatsOverview stats={stats} />
            <TimelineChart />
          </section>
        )}
      </div>
    </main>
  )
}
