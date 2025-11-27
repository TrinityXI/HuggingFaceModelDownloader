'use client'

import { useEffect, useState } from 'react'
import axios from 'axios'
import { Activity, Download, AlertCircle, CheckCircle, Clock, XCircle } from 'lucide-react'
import StatsOverview from '@/components/StatsOverview'
import QueueList from '@/components/QueueList'
import TimelineChart from '@/components/TimelineChart'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api'

export default function Home() {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'all' | 'pending' | 'downloading' | 'completed' | 'failed'>('all')

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
    const interval = setInterval(fetchStats, 10000) // 每10秒刷新一次
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            <Activity className="w-8 h-8 text-blue-600" />
            HuggingFace Downloader Monitor
          </h1>
          <p className="mt-2 text-gray-600">Real-time monitoring of download queue and datasets</p>
        </div>

        {/* Stats Overview */}
        <StatsOverview stats={stats} />

        {/* Timeline Chart */}
        <div className="mt-8">
          <TimelineChart />
        </div>

        {/* Queue Tabs */}
        <div className="mt-8">
          <div className="border-b border-gray-200">
            <nav className="-mb-px flex space-x-8">
              {[
                { key: 'all', label: 'All Tasks', icon: Activity },
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
                      flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm
                      ${activeTab === tab.key
                        ? 'border-blue-500 text-blue-600'
                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                      }
                    `}
                  >
                    <Icon className="w-4 h-4" />
                    {tab.label}
                    <span className={`
                      px-2 py-0.5 rounded-full text-xs
                      ${activeTab === tab.key ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'}
                    `}>
                      {count}
                    </span>
                  </button>
                )
              })}
            </nav>
          </div>

          {/* Queue List */}
          <div className="mt-6">
            <QueueList status={activeTab === 'all' ? undefined : activeTab} />
          </div>
        </div>
      </div>
    </main>
  )
}
