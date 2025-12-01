'use client'

import { useState, useEffect } from 'react'
import axios from 'axios'
import { Settings, Save, RefreshCw, AlertCircle, CheckCircle, X, Calendar, Hash, Clock, Globe } from 'lucide-react'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api'

interface ScanConfig {
  producer_interval: number
  producer_days: number
  producer_limit: number
  producer_timezone_offset: number
  producer_use_created_at: boolean
  producer_auto_limit: boolean
  hf_endpoint: string
}

interface ScanSettingsProps {
  isOpen: boolean
  onClose: () => void
}

export default function ScanSettings({ isOpen, onClose }: ScanSettingsProps) {
  const [config, setConfig] = useState<ScanConfig>({
    producer_interval: 3600,
    producer_days: 7,
    producer_limit: 50,
    producer_timezone_offset: 8,
    producer_use_created_at: false,
    producer_auto_limit: true,
    hf_endpoint: 'https://hf-mirror.com'
  })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // 加载配置
  const loadConfig = async () => {
    try {
      setLoading(true)
      setError('')
      const response = await axios.get(`${API_BASE_URL}/scan/config`)
      setConfig(response.data)
    } catch (err: any) {
      console.error('Failed to load config:', err)
      setError('加载配置失败: ' + (err.response?.data?.error || err.message))
    } finally {
      setLoading(false)
    }
  }

  // 保存配置
  const saveConfig = async () => {
    try {
      setSaving(true)
      setError('')
      setSuccess('')
      await axios.post(`${API_BASE_URL}/scan/config`, config)
      setSuccess('配置已保存，将在下一次扫描时生效')
      setTimeout(() => setSuccess(''), 3000)
    } catch (err: any) {
      console.error('Failed to save config:', err)
      setError('保存配置失败: ' + (err.response?.data?.error || err.message))
    } finally {
      setSaving(false)
    }
  }

  // 重置为默认配置
  const resetToDefaults = async () => {
    try {
      setSaving(true)
      setError('')
      setSuccess('')
      const response = await axios.post(`${API_BASE_URL}/scan/config/reset`)
      setConfig(response.data)
      setSuccess('配置已重置为默认值')
      setTimeout(() => setSuccess(''), 3000)
    } catch (err: any) {
      console.error('Failed to reset config:', err)
      setError('重置配置失败: ' + (err.response?.data?.error || err.message))
    } finally {
      setSaving(false)
    }
  }

  // 手动触发扫描
  const triggerScan = async () => {
    try {
      setSaving(true)
      setError('')
      setSuccess('')
      await axios.post(`${API_BASE_URL}/scan/trigger`)
      setSuccess('已触发扫描任务')
      setTimeout(() => setSuccess(''), 3000)
    } catch (err: any) {
      console.error('Failed to trigger scan:', err)
      setError('触发扫描失败: ' + (err.response?.data?.error || err.message))
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    if (isOpen) {
      loadConfig()
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
            <Settings className="w-5 h-5 mr-2" />
            数据集扫描配置
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
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              <span className="ml-3 text-gray-600 dark:text-gray-400">加载配置中...</span>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md dark:bg-red-900/20 dark:border-red-800">
                  <div className="flex items-center">
                    <AlertCircle className="w-4 h-4 text-red-500 mr-2" />
                    <span className="text-red-700 dark:text-red-400 text-sm">{error}</span>
                  </div>
                </div>
              )}

              {success && (
                <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-md dark:bg-green-900/20 dark:border-green-800">
                  <div className="flex items-center">
                    <CheckCircle className="w-4 h-4 text-green-500 mr-2" />
                    <span className="text-green-700 dark:text-green-400 text-sm">{success}</span>
                  </div>
                </div>
              )}

              <div className="space-y-6">
                {/* 扫描间隔 */}
                <div>
                  <label className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    <Clock className="w-4 h-4 mr-2" />
                    扫描间隔 (秒)
                  </label>
                  <input
                    type="number"
                    value={config.producer_interval}
                    onChange={(e) => setConfig({...config, producer_interval: parseInt(e.target.value) || 3600})}
                    min="60"
                    max="86400"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    两次扫描之间的间隔时间，推荐 3600 秒（1小时）
                  </p>
                </div>

                {/* 扫描天数 */}
                <div>
                  <label className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    <Calendar className="w-4 h-4 mr-2" />
                    扫描天数
                  </label>
                  <input
                    type="number"
                    value={config.producer_days}
                    onChange={(e) => setConfig({...config, producer_days: parseInt(e.target.value) || 7})}
                    min="1"
                    max="365"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    扫描最近多少天创建/更新的数据集
                  </p>
                </div>

                {/* 每次扫描数量限制 */}
                <div>
                  <label className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    <Hash className="w-4 h-4 mr-2" />
                    每次扫描数量限制
                  </label>
                  <input
                    type="number"
                    value={config.producer_limit}
                    onChange={(e) => setConfig({...config, producer_limit: parseInt(e.target.value) || 50})}
                    min="1"
                    max="1000"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    每次扫描最多处理多少个数据集
                  </p>
                </div>

                {/* 时区偏移 */}
                <div>
                  <label className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    <Globe className="w-4 h-4 mr-2" />
                    时区偏移 (小时)
                  </label>
                  <input
                    type="number"
                    value={config.producer_timezone_offset}
                    onChange={(e) => setConfig({...config, producer_timezone_offset: parseInt(e.target.value) || 8})}
                    min="-12"
                    max="12"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    相对 UTC 的时区偏移，中国为 8
                  </p>
                </div>

                {/* HuggingFace 端点 */}
                <div>
                  <label className="flex items-center text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                    <Globe className="w-4 h-4 mr-2" />
                    HuggingFace 端点
                  </label>
                  <input
                    type="text"
                    value={config.hf_endpoint}
                    onChange={(e) => setConfig({...config, hf_endpoint: e.target.value})}
                    placeholder="https://huggingface.co"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                  />
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    HuggingFace API 端点，可使用镜像如 https://hf-mirror.com
                  </p>
                </div>

                {/* 切换选项 */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                        使用创建时间过滤
                      </label>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        使用 createdAt 而非 lastModified 过滤数据集
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setConfig({...config, producer_use_created_at: !config.producer_use_created_at})}
                      className={`
                        relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent 
                        transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
                        ${config.producer_use_created_at ? 'bg-blue-600' : 'bg-gray-200 dark:bg-gray-600'}
                      `}
                    >
                      <span
                        className={`
                          pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 
                          transition duration-200 ease-in-out
                          ${config.producer_use_created_at ? 'translate-x-5' : 'translate-x-0'}
                        `}
                      />
                    </button>
                  </div>

                  <div className="flex items-center justify-between">
                    <div>
                      <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                        自动限制模式
                      </label>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        自动调整查询限制以获取目标数量的数据集
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setConfig({...config, producer_auto_limit: !config.producer_auto_limit})}
                      className={`
                        relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent 
                        transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2
                        ${config.producer_auto_limit ? 'bg-blue-600' : 'bg-gray-200 dark:bg-gray-600'}
                      `}
                    >
                      <span
                        className={`
                          pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 
                          transition duration-200 ease-in-out
                          ${config.producer_auto_limit ? 'translate-x-5' : 'translate-x-0'}
                        `}
                      />
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
          <div className="flex gap-2">
            <button
              onClick={resetToDefaults}
              disabled={saving || loading}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 dark:bg-gray-600 dark:text-gray-200 dark:border-gray-500 dark:hover:bg-gray-500"
            >
              <RefreshCw className="w-4 h-4 inline mr-1" />
              重置默认
            </button>
            <button
              onClick={triggerScan}
              disabled={saving || loading}
              className="px-4 py-2 text-sm font-medium text-white bg-green-600 border border-transparent rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50"
            >
              <RefreshCw className="w-4 h-4 inline mr-1" />
              立即扫描
            </button>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 dark:bg-gray-600 dark:text-gray-200 dark:border-gray-500 dark:hover:bg-gray-500"
            >
              取消
            </button>
            <button
              onClick={saveConfig}
              disabled={saving || loading}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
            >
              {saving ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white inline mr-2"></div>
                  保存中...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 inline mr-1" />
                  保存配置
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
