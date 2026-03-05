'use client'

import { TrendingUp, Download, CheckCircle, XCircle, Clock } from 'lucide-react'

interface StatsOverviewProps {
  stats: any
}

export default function StatsOverview({ stats }: StatsOverviewProps) {
  if (!stats) return null

  const cards = [
    {
      title: 'Pending',
      value: stats.status_counts?.pending || 0,
      icon: Clock,
      accent: 'text-amber-600',
      bg: 'bg-amber-50',
      ring: 'ring-amber-100',
    },
    {
      title: 'Downloading',
      value: stats.status_counts?.downloading || 0,
      icon: Download,
      accent: 'text-accent',
      bg: 'bg-accent-light',
      ring: 'ring-accent/10',
    },
    {
      title: 'Completed',
      value: stats.status_counts?.completed || 0,
      icon: CheckCircle,
      accent: 'text-emerald-600',
      bg: 'bg-emerald-50',
      ring: 'ring-emerald-100',
    },
    {
      title: 'Failed',
      value: stats.failed_count || 0,
      icon: XCircle,
      accent: 'text-rose-600',
      bg: 'bg-rose-50',
      ring: 'ring-rose-100',
    },
    {
      title: 'Added today',
      value: stats.today_added || 0,
      icon: TrendingUp,
      accent: 'text-violet-600',
      bg: 'bg-violet-50',
      ring: 'ring-violet-100',
    },
    {
      title: 'Completed today',
      value: stats.today_completed || 0,
      icon: CheckCircle,
      accent: 'text-teal-600',
      bg: 'bg-teal-50',
      ring: 'ring-teal-100',
    },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      {cards.map((card, i) => {
        const Icon = card.icon
        return (
          <div
            key={card.title}
            className="card-interactive bg-surface rounded-2xl shadow-soft p-5 ring-1 ring-surface-border/50"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <div className="flex items-center gap-2.5 mb-3">
              <div className={`${card.bg} ${card.ring} p-1.5 rounded-lg ring-1`}>
                <Icon className={`w-3.5 h-3.5 ${card.accent}`} />
              </div>
              <p className="text-xs font-medium text-ink-secondary tracking-wide uppercase">{card.title}</p>
            </div>
            <p className="text-2xl font-semibold text-ink tabular-nums tracking-tight">{card.value}</p>
          </div>
        )
      })}
    </div>
  )
}
