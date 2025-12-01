'use client'

import { useEffect, useState } from 'react'
import axios from 'axios'
import { Download, CheckCircle, XCircle, Clock, RefreshCw, Trash2, ExternalLink, Folder, Filter, X, FolderOpen } from 'lucide-react'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api'

interface QueueListProps {
  status?: string
}

export default function QueueList({ status }: QueueListProps) {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)

  // Filter states
  const [filterStatus, setFilterStatus] = useState<string>(status || '')
  const [filterDatasetId, setFilterDatasetId] = useState<string>('')
  const [filterPriority, setFilterPriority] = useState<string>('')
  const [showFilters, setShowFilters] = useState(false)

  const fetchTasks = async () => {
    try {
      setLoading(true)
      const params: any = { page, per_page: 20 }

      // Apply filters
      if (filterStatus) params.status = filterStatus
      if (filterDatasetId) params.dataset_id = filterDatasetId
      if (filterPriority) params.priority = filterPriority

      const response = await axios.get(`${API_BASE_URL}/queue/list`, { params })
      setTasks(response.data.tasks)
      setTotalPages(response.data.total_pages)
      setLoading(false)
    } catch (error) {
      console.error('Failed to fetch tasks:', error)
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTasks()
  }, [page, filterStatus, filterDatasetId, filterPriority])

  // Sync filterStatus with status prop when it changes
  useEffect(() => {
    setFilterStatus(status || '')
  }, [status])

  const resetFilters = () => {
    setFilterStatus('')
    setFilterDatasetId('')
    setFilterPriority('')
    setPage(1)
  }

  const hasActiveFilters = filterStatus || filterDatasetId || filterPriority

  const handleRetry = async (taskId: number) => {
    try {
      await axios.post(`${API_BASE_URL}/queue/${taskId}/retry`)
      fetchTasks()
    } catch (error) {
      console.error('Failed to retry task:', error)
    }
  }

  const handleDelete = async (taskId: number) => {
    if (!confirm('Are you sure you want to delete this task?')) return

    try {
      await axios.delete(`${API_BASE_URL}/queue/${taskId}`)
      fetchTasks()
    } catch (error) {
      console.error('Failed to delete task:', error)
    }
  }

  const handleOpenSMB = (storagePath: string) => {
    if (!storagePath) {
      alert('No storage path available for this task')
      return
    }

    const isMac = navigator.userAgent.includes('Mac')

    if (isMac) {
      // macOS: Open directly using smb:// protocol
      const smbPath = `smb://158.132.113.88/infixai${storagePath}`
      window.location.href = smbPath
    } else {
      // Windows: Copy UNC path to clipboard
      const winPath = `\\\\158.132.113.88\\infixai${storagePath.replace(/\//g, '\\')}`
      
      navigator.clipboard.writeText(winPath)
        .then(() => {
          alert(`Path copied to clipboard:\n${winPath}\n\nPlease paste it in File Explorer.`)
        })
        .catch(() => {
          prompt('Copy this path to File Explorer:', winPath)
        })
    }
  }

  const getStatusBadge = (status: string) => {
    const configs: Record<string, { color: string; icon: any; label: string }> = {
      pending: { color: 'bg-yellow-100 text-yellow-800', icon: Clock, label: 'Pending' },
      downloading: { color: 'bg-blue-100 text-blue-800', icon: Download, label: 'Downloading' },
      completed: { color: 'bg-green-100 text-green-800', icon: CheckCircle, label: 'Completed' },
      failed: { color: 'bg-red-100 text-red-800', icon: XCircle, label: 'Failed' },
    }
    
    const config = configs[status] || configs.pending
    const Icon = config.icon
    
    return (
      <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${config.color}`}>
        <Icon className="w-3 h-3" />
        {config.label}
      </span>
    )
  }

  if (loading) {
    return (
      <div className="text-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
      </div>
    )
  }

  return (
    <div>
      {/* Filter Section */}
      <div className="mb-4 bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Filter className="w-5 h-5 text-gray-600" />
            <h3 className="text-lg font-medium text-gray-900">Filters</h3>
            {hasActiveFilters && (
              <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
                Active
              </span>
            )}
          </div>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="text-sm text-blue-600 hover:text-blue-800"
          >
            {showFilters ? 'Hide' : 'Show'}
          </button>
        </div>

        {showFilters && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Status Filter */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Status
                </label>
                <select
                  value={filterStatus}
                  onChange={(e) => {
                    setFilterStatus(e.target.value)
                    setPage(1)
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All Status</option>
                  <option value="pending">Pending</option>
                  <option value="downloading">Downloading</option>
                  <option value="completed">Completed</option>
                  <option value="failed">Failed</option>
                </select>
              </div>

              {/* Dataset ID Filter */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Dataset ID
                </label>
                <input
                  type="text"
                  value={filterDatasetId}
                  onChange={(e) => {
                    setFilterDatasetId(e.target.value)
                    setPage(1)
                  }}
                  placeholder="Search by dataset ID..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Priority Filter */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Priority
                </label>
                <select
                  value={filterPriority}
                  onChange={(e) => {
                    setFilterPriority(e.target.value)
                    setPage(1)
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">All Priorities</option>
                  <option value="1">1 (Highest)</option>
                  <option value="2">2</option>
                  <option value="3">3</option>
                  <option value="4">4</option>
                  <option value="5">5 (Lowest)</option>
                </select>
              </div>
            </div>

            {/* Reset Button */}
            {hasActiveFilters && (
              <div className="flex justify-end">
                <button
                  onClick={resetFilters}
                  className="inline-flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-md text-sm font-medium transition-colors"
                >
                  <X className="w-4 h-4" />
                  Reset Filters
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {tasks.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg shadow">
          <p className="text-gray-500">No tasks found</p>
        </div>
      ) : (
        <div className="bg-white shadow overflow-x-auto sm:rounded-lg">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/5 min-w-[200px]">
                  Dataset ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-32">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-1/4 min-w-[250px]">
                  Storage Path
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-20">
                  Priority
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-40">
                  Created At
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                  Retry Count
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-24">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {tasks.map((task) => (
                <tr key={task.id} className="hover:bg-gray-50">
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-gray-900 truncate" title={task.dataset_id}>
                          {task.dataset_id}
                        </div>
                        {task.last_error && (
                          <div className="text-xs text-red-600 mt-1 truncate" title={task.last_error}>
                            {task.last_error}
                          </div>
                        )}
                      </div>
                      <a
                        href={`https://huggingface.co/datasets/${task.dataset_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:text-blue-800 flex-shrink-0"
                        title="View on HuggingFace"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </a>
                    </div>
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap">
                    {getStatusBadge(task.status)}
                  </td>
                  <td className="px-4 py-4">
                    {task.storage_path ? (
                      <div className="flex items-center gap-2 text-sm text-gray-600 min-w-0">
                        <Folder className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <span className="truncate flex-1" title={task.storage_path}>
                          {task.storage_path}
                        </span>
                        <button
                          onClick={() => handleOpenSMB(task.storage_path)}
                          className="text-green-600 hover:text-green-900 flex-shrink-0"
                          title="Open in SMB"
                        >
                          <FolderOpen className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      <span className="text-sm text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                    {task.priority}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500">
                    {new Date(task.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm text-gray-500 text-center">
                    {task.retry_count}
                  </td>
                  <td className="px-4 py-4 whitespace-nowrap text-sm font-medium">
                    <div className="flex gap-2 justify-center">
                      {task.status === 'failed' && (
                        <button
                          onClick={() => handleRetry(task.id)}
                          className="text-blue-600 hover:text-blue-900"
                          title="Retry"
                        >
                          <RefreshCw className="w-4 h-4" />
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(task.id)}
                        className="text-red-600 hover:text-red-900"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      <div className="mt-4 flex items-center justify-between">
        <div className="text-sm text-gray-700">
          Page {page} of {totalPages}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
