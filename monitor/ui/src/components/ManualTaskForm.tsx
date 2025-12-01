'use client'

import { useState, useEffect } from 'react'
import axios from 'axios'
import { Search, Plus, Folder, Star, AlertCircle, X } from 'lucide-react'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api'

interface Dataset {
  id: string
  name: string
  description: string
  downloads: number
  likes: number
  last_modified: string
  created_at: string
  tags: string[]
  author: string
}

interface ManualTaskFormProps {
  isOpen: boolean
  onClose: () => void
  onTaskAdded: () => void
}

export default function ManualTaskForm({ isOpen, onClose, onTaskAdded }: ManualTaskFormProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null)
  const [storagePath, setStoragePath] = useState('')
  const [priority, setPriority] = useState(0)
  const [loading, setLoading] = useState(false)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('')
      setDatasets([])
      setSelectedDataset(null)
      setStoragePath('')
      setPriority(0)
      setError('')
      setSuccess('')
    }
  }, [isOpen])

  const searchDatasets = async (query: string) => {
    if (!query.trim()) {
      setDatasets([])
      return
    }

    try {
      setSearching(true)
      const response = await axios.get(`${API_BASE_URL}/datasets/search`, {
        params: { q: query, limit: 10 }
      })
      setDatasets(response.data.datasets)
      setError('')
    } catch (error) {
      console.error('Failed to search datasets:', error)
      setError('搜索数据集失败，请检查网络连接')
      setDatasets([])
    } finally {
      setSearching(false)
    }
  }

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      searchDatasets(searchQuery)
    }, 500)

    return () => clearTimeout(timeoutId)
  }, [searchQuery])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!selectedDataset) {
      setError('请选择数据集')
      return
    }

    // if (!storagePath.trim()) {
    //   setError('请输入存储路径')
    //   return
    // }

    try {
      setLoading(true)
      setError('')
      setSuccess('')

      const response = await axios.post(`${API_BASE_URL}/queue/manual`, {
        dataset_id: selectedDataset.id,
        storage_path: storagePath,
        priority: priority
      })

      setSuccess(`任务创建成功: ${selectedDataset.id}`)

      // 回调通知父组件
      if (onTaskAdded) {
        onTaskAdded()
      }
      
      // 延迟关闭
      setTimeout(() => {
        onClose()
      }, 1500)

    } catch (error: any) {
      console.error('Failed to create task:', error)
      const errorMessage = error.response?.data?.error || '创建任务失败'
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  const formatNumber = (num: number) => {
    if (num >= 1000000) {
      return (num / 1000000).toFixed(1) + 'M'
    } else if (num >= 1000) {
      return (num / 1000).toFixed(1) + 'K'
    }
    return num.toString()
  }

  const formatDate = (dateString: string) => {
    if (!dateString) return '未知'
    return new Date(dateString).toLocaleDateString('zh-CN')
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
            <Plus className="w-5 h-5 mr-2" />
            手动添加下载任务
          </h2>
          <button 
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto">
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
              <div className="flex items-center">
                <AlertCircle className="w-4 h-4 text-red-500 mr-2" />
                <span className="text-red-700 text-sm">{error}</span>
              </div>
            </div>
          )}

          {success && (
            <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-md">
              <span className="text-green-700 text-sm">{success}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* 数据集搜索 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                搜索数据集
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="输入数据集名称..."
                  className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                />
              </div>

              {/* 搜索结果 */}
              {searchQuery && !selectedDataset && (
                <div className="mt-2 max-h-60 overflow-y-auto border border-gray-200 rounded-md dark:border-gray-600">
                  {searching ? (
                    <div className="p-4 text-center text-gray-500 dark:text-gray-400">
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600 mx-auto"></div>
                      <p className="mt-2 text-sm">搜索中...</p>
                    </div>
                  ) : datasets.length > 0 ? (
                    <div className="divide-y divide-gray-100 dark:divide-gray-700">
                      {datasets.map((dataset) => (
                        <div
                          key={dataset.id}
                          className={`p-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 ${
                            selectedDataset && (selectedDataset as Dataset).id === dataset.id ? 'bg-blue-50 border-l-2 border-blue-500 dark:bg-blue-900/20' : ''
                          }`}
                          onClick={() => {
                            setSelectedDataset(dataset)
                            setSearchQuery('') // Clear search query to hide list
                          }}
                        >
                          <div className="flex justify-between items-start">
                            <div className="flex-1">
                              <h3 className="text-sm font-medium text-gray-900 dark:text-white">{dataset.id}</h3>
                              {dataset.description && (
                                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-2">
                                  {dataset.description}
                                </p>
                              )}
                              <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 dark:text-gray-400">
                                <span>下载: {formatNumber(dataset.downloads)}</span>
                                <span>点赞: {formatNumber(dataset.likes)}</span>
                                <span>创建: {formatDate(dataset.created_at)}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="p-4 text-center text-gray-500 dark:text-gray-400">
                      <p className="text-sm">未找到匹配的数据集</p>
                    </div>
                  )}
                </div>
              )}

              {selectedDataset && (
                <div className="mt-2 p-3 bg-blue-50 border border-blue-200 rounded-md dark:bg-blue-900/20 dark:border-blue-800">
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-medium text-blue-900 dark:text-blue-100">
                      已选择: {selectedDataset.id}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedDataset(null)
                        setSearchQuery('')
                      }}
                      className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
                    >
                      取消选择
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* 存储路径 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                <Folder className="w-4 h-4 inline mr-1" />
                NAS 存储路径 (可选)
              </label>
              <input
                type="text"
                value={storagePath}
                onChange={(e) => setStoragePath(e.target.value)}
                placeholder="例如: datasets/bert-base-uncased (留空使用默认)"
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white"
              />
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                相对于 NAS 存储根目录的相对路径
              </p>
            </div>

            {/* 优先级 */}
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                <Star className="w-4 h-4 inline mr-1" />
                下载优先级: {priority}
              </label>
              <div className="flex items-center gap-4">
                <input
                  type="range"
                  min="0"
                  max="10"
                  value={priority}
                  onChange={(e) => setPriority(parseInt(e.target.value))}
                  className="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
                />
              </div>
              <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mt-1">
                <span>低优先级 (0)</span>
                <span>高优先级 (10)</span>
              </div>
            </div>

            {/* 提交按钮 */}
            <div className="pt-4">
              <button
                type="submit"
                disabled={loading || !selectedDataset}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white py-2 px-4 rounded-md transition-colors flex items-center justify-center"
              >
                {loading ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    创建中...
                  </>
                ) : (
                  <>
                    <Plus className="w-4 h-4 mr-2" />
                    创建下载任务
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
