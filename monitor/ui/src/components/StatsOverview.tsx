'use client'

import { TrendingUp, Download, CheckCircle, XCircle, Clock } from 'lucide-react'

interface StatsOverviewProps {
  stats: any
}

export default function StatsOverview({ stats }: StatsOverviewProps) {
  if (!stats) return null

  const cards = [
    {
      title: 'Total Pending',
      value: stats.status_counts?.pending || 0,
      icon: Clock,
      color: 'text-yellow-600',
      bgColor: 'bg-yellow-50',
    },
    {
      title: 'Downloading',
      value: stats.status_counts?.downloading || 0,
      icon: Download,
      color: 'text-blue-600',
      bgColor: 'bg-blue-50',
    },
    {
      title: 'Completed',
      value: stats.status_counts?.completed || 0,
      icon: CheckCircle,
      color: 'text-green-600',
      bgColor: 'bg-green-50',
    },
    {
      title: 'Failed',
      value: stats.failed_count || 0,
      icon: XCircle,
      color: 'text-red-600',
      bgColor: 'bg-red-50',
    },
    {
      title: 'Today Added',
      value: stats.today_added || 0,
      icon: TrendingUp,
      color: 'text-purple-600',
      bgColor: 'bg-purple-50',
    },
    {
      title: 'Today Completed',
      value: stats.today_completed || 0,
      icon: CheckCircle,
      color: 'text-teal-600',
      bgColor: 'bg-teal-50',
    },
  ]

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {cards.map((card) => {
        const Icon = card.icon
        return (
          <div key={card.title} className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">{card.title}</p>
                <p className="mt-2 text-3xl font-bold text-gray-900">{card.value}</p>
              </div>
              <div className={`${card.bgColor} p-3 rounded-lg`}>
                <Icon className={`w-6 h-6 ${card.color}`} />
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
