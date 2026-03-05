'use client'

import { useEffect, useState } from 'react'
import axios from 'axios'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api'

export default function TimelineChart() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await axios.get(`${API_BASE_URL}/stats/timeline`, {
          params: { days: 7 }
        })
        
        const dateMap = new Map()
        
        response.data.completed_timeline.forEach((item: any) => {
          if (!dateMap.has(item.date)) {
            dateMap.set(item.date, { date: item.date, completed: 0, created: 0 })
          }
          dateMap.get(item.date).completed = item.count
        })
        
        response.data.created_timeline.forEach((item: any) => {
          if (!dateMap.has(item.date)) {
            dateMap.set(item.date, { date: item.date, completed: 0, created: 0 })
          }
          dateMap.get(item.date).created = item.count
        })
        
        const chartData = Array.from(dateMap.values()).sort((a, b) => 
          new Date(a.date).getTime() - new Date(b.date).getTime()
        )
        
        setData(chartData)
        setLoading(false)
      } catch (error) {
        console.error('Failed to fetch timeline data:', error)
        setLoading(false)
      }
    }
    
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="bg-surface rounded-2xl shadow-soft ring-1 ring-surface-border/50 p-6">
        <div className="h-4 w-56 skeleton mb-6" />
        <div className="h-[300px] flex flex-col justify-between">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-px bg-surface-sunken" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="bg-surface rounded-2xl shadow-soft ring-1 ring-surface-border/50 p-6">
      <h3 className="text-base font-semibold text-ink tracking-tight mb-6">Activity timeline — last 7 days</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e8e6e1" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 12, fill: '#a39e99' }}
            tickLine={false}
            axisLine={{ stroke: '#e8e6e1' }}
          />
          <YAxis
            tick={{ fontSize: 12, fill: '#a39e99' }}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#fff',
              border: '1px solid #e8e6e1',
              borderRadius: '12px',
              boxShadow: '0 4px 16px rgba(28, 25, 23, 0.08)',
              fontSize: '13px',
              padding: '10px 14px',
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: '13px', paddingTop: '16px' }}
          />
          <Line
            type="monotone"
            dataKey="created"
            stroke="#7c6fbb"
            name="Created"
            strokeWidth={2}
            dot={{ fill: '#7c6fbb', r: 3, strokeWidth: 0 }}
            activeDot={{ r: 5, fill: '#7c6fbb', stroke: '#fff', strokeWidth: 2 }}
          />
          <Line
            type="monotone"
            dataKey="completed"
            stroke="#3c9f80"
            name="Completed"
            strokeWidth={2}
            dot={{ fill: '#3c9f80', r: 3, strokeWidth: 0 }}
            activeDot={{ r: 5, fill: '#3c9f80', stroke: '#fff', strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
