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
        
        // 合并 completed 和 created 数据
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
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Activity Timeline (Last 7 Days)</h3>
        <div className="h-64 flex items-center justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Activity Timeline (Last 7 Days)</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="created" stroke="#8b5cf6" name="Created" strokeWidth={2} />
          <Line type="monotone" dataKey="completed" stroke="#10b981" name="Completed" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
