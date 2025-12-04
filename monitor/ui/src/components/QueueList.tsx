'use client'

import { useEffect, useState, useMemo } from 'react'
import axios from 'axios'
import { 
  useReactTable, 
  getCoreRowModel, 
  flexRender, 
  PaginationState,
  ColumnDef,
  ColumnFiltersState,
  Column
} from '@tanstack/react-table'
import { 
  Download, 
  CheckCircle, 
  XCircle, 
  Clock, 
  RefreshCw, 
  Trash2, 
  ExternalLink, 
  Folder, 
  FolderOpen,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight
} from 'lucide-react'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080/api'

interface Task {
  id: number
  dataset_id: string
  status: string
  storage_path: string
  priority: number
  created_at: string
  retry_count: number
  last_error?: string
  progress?: {
    percentage: number
    downloaded_bytes: number
    total_bytes: number
    total_files: number
    completed_files: number
    skipped_files: number
    active_files: number
    download_speed: number
    estimated_remaining: number
    progress_status?: string
  }
}

interface QueueListProps {
  status?: string
}

// Debounced Input Component
function DebouncedInput({
  value: initialValue,
  onChange,
  debounce = 500,
  ...props
}: {
  value: string | number
  onChange: (value: string | number) => void
  debounce?: number
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange'>) {
  const [value, setValue] = useState(initialValue)

  useEffect(() => {
    setValue(initialValue)
  }, [initialValue])

  useEffect(() => {
    const timeout = setTimeout(() => {
      onChange(value)
    }, debounce)

    return () => clearTimeout(timeout)
  }, [value])

  return (
    <input {...props} value={value} onChange={e => setValue(e.target.value)} />
  )
}

function Filter({ column }: { column: Column<any, unknown> }) {
  const columnFilterValue = column.getFilterValue()
  const { id } = column

  if (id === 'dataset_id') {
    return (
      <DebouncedInput
        type="text"
        value={(columnFilterValue as string) ?? ''}
        onChange={value => column.setFilterValue(value)}
        placeholder="Search..."
        className="w-full px-2 py-1 text-xs font-normal border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
        onClick={e => e.stopPropagation()}
      />
    )
  }

  if (id === 'status') {
    return (
      <select
        value={(columnFilterValue as string) ?? ''}
        onChange={e => column.setFilterValue(e.target.value)}
        className="w-full px-2 py-1 text-xs font-normal border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
        onClick={e => e.stopPropagation()}
      >
        <option value="">All</option>
        <option value="pending">Pending</option>
        <option value="downloading">Downloading</option>
        <option value="completed">Completed</option>
        <option value="failed">Failed</option>
      </select>
    )
  }

  if (id === 'priority') {
    return (
      <select
        value={(columnFilterValue as string) ?? ''}
        onChange={e => column.setFilterValue(e.target.value)}
        className="w-full px-2 py-1 text-xs font-normal border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
        onClick={e => e.stopPropagation()}
      >
        <option value="">All</option>
        <option value="1">1 (Highest)</option>
        <option value="2">2</option>
        <option value="3">3</option>
        <option value="4">4</option>
        <option value="5">5 (Lowest)</option>
      </select>
    )
  }

  return null
}

export default function QueueList({ status }: QueueListProps) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [totalPages, setTotalPages] = useState(1)
  
  // Table state
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 20,
  })
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>(
    status ? [{ id: 'status', value: status }] : []
  )
  
  // Fetch progress for downloading tasks
  const fetchProgress = async (task: Task) => {
    if (task.status !== 'downloading') return
    
    try {
      const response = await axios.get(`${API_BASE_URL}/queue/${task.id}/progress`)
      setTasks(prev => prev.map(t => 
        t.id === task.id ? { ...t, progress: response.data } : t
      ))
    } catch (error) {
      console.error(`Failed to fetch progress for task ${task.id}:`, error)
    }
  }
  
  // Poll progress for downloading tasks every 3 seconds
  useEffect(() => {
    const downloadingTasks = tasks.filter(t => t.status === 'downloading')
    if (downloadingTasks.length === 0) return
    
    const interval = setInterval(() => {
      downloadingTasks.forEach(task => fetchProgress(task))
    }, 3000)
    
    return () => clearInterval(interval)
  }, [tasks])

  const fetchTasks = async () => {
    try {
      setLoading(true)
      const params: any = { 
        page: pagination.pageIndex + 1, 
        per_page: pagination.pageSize 
      }

      const statusFilter = columnFilters.find(f => f.id === 'status')?.value
      const datasetIdFilter = columnFilters.find(f => f.id === 'dataset_id')?.value
      const priorityFilter = columnFilters.find(f => f.id === 'priority')?.value

      if (statusFilter) params.status = statusFilter
      if (datasetIdFilter) params.dataset_id = datasetIdFilter
      if (priorityFilter) params.priority = priorityFilter

      const response = await axios.get(`${API_BASE_URL}/queue/list`, { params })
      setTasks(response.data.tasks)
      setTotalPages(response.data.total_pages)
    } catch (error) {
      console.error('Failed to fetch tasks:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTasks()
  }, [pagination.pageIndex, pagination.pageSize, columnFilters])

  useEffect(() => {
    setColumnFilters(prev => {
      const otherFilters = prev.filter(f => f.id !== 'status')
      return status ? [...otherFilters, { id: 'status', value: status }] : otherFilters
    })
    setPagination(prev => ({ ...prev, pageIndex: 0 }))
  }, [status])

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
      const smbPath = `smb://158.132.113.88/infixai${storagePath}`
      window.location.href = smbPath
    } else {
      const winPath = `\\\\158.132.113.88\\infixai${storagePath.replace(/\//g, '\\')}`
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(winPath)
          .then(() => alert(`Path copied to clipboard:\n${winPath}\n\nPlease paste it in File Explorer.`))
          .catch(() => prompt('Copy this path to File Explorer:', winPath))
      } else {
        prompt('Copy this path to File Explorer:', winPath)
      }
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

  const columns = useMemo<ColumnDef<Task>[]>(
    () => [
      {
        accessorKey: 'dataset_id',
        header: ({ column }) => (
          <div className="flex flex-col gap-2 pb-2">
            <span>Dataset ID</span>
            <Filter column={column} />
          </div>
        ),
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-gray-900 truncate" title={row.original.dataset_id}>
                {row.original.dataset_id}
              </div>
              {row.original.last_error && (
                <div className="text-xs text-red-600 mt-1 truncate" title={row.original.last_error}>
                  {row.original.last_error}
                </div>
              )}
            </div>
            <a
              href={`https://huggingface.co/datasets/${row.original.dataset_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:text-blue-800 flex-shrink-0"
              title="View on HuggingFace"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          </div>
        ),
      },
      {
        accessorKey: 'status',
        header: ({ column }) => (
          <div className="flex flex-col gap-2 pb-2">
            <span>Status</span>
            <Filter column={column} />
          </div>
        ),
        cell: ({ getValue }) => getStatusBadge(getValue() as string),
      },
      {
        id: 'progress',
        header: 'Progress',
        cell: ({ row }) => {
          if (row.original.status !== 'downloading' || !row.original.progress) {
            return <span className="text-sm text-gray-400">-</span>
          }
          
          const progress = row.original.progress
          const progressStatus = progress.progress_status || 'downloading'
          const isScanning = progressStatus === 'scanning'
          
          return (
            <div className="min-w-[200px] space-y-1">
              {/* Progress Status Badge */}
              <div className="flex items-center justify-between text-xs">
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                  isScanning 
                    ? 'bg-purple-100 text-purple-700' 
                    : 'bg-blue-100 text-blue-700'
                }`}>
                  {isScanning ? (
                    <>
                      <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Scanning
                    </>
                  ) : (
                    <>
                      <Download className="w-3 h-3" />
                      Downloading
                    </>
                  )}
                </span>
                <span className="font-medium text-blue-600">
                  {isScanning ? `${progress.total_files} files found` : `${progress.percentage.toFixed(1)}%`}
                </span>
              </div>
              {/* File Progress */}
              <div className="flex items-center justify-between text-xs text-gray-600">
                <span>
                  {progress.completed_files}/{progress.total_files} files
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                <div 
                  className={`h-2 rounded-full transition-all duration-300 ${
                    isScanning ? 'bg-purple-500 animate-pulse' : 'bg-blue-600'
                  }`}
                  style={{ width: isScanning ? '100%' : `${Math.min(100, progress.percentage)}%` }}
                />
              </div>
              {!isScanning && (
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>
                  {(progress.download_speed / 1024 / 1024).toFixed(2)} MB/s
                </span>
                {progress.estimated_remaining > 0 && (
                  <span>
                    ETA: {Math.floor(progress.estimated_remaining / 60)}m {Math.floor(progress.estimated_remaining % 60)}s
                  </span>
                )}
              </div>
              )}
            </div>
          )
        },
      },
      {
        accessorKey: 'storage_path',
        header: 'Storage Path',
        cell: ({ row }) => {
          const path = row.original.storage_path
          return path ? (
            <div className="flex items-center gap-2 text-sm text-gray-600 min-w-0">
              <Folder className="w-4 h-4 text-gray-400 flex-shrink-0" />
              <span className="truncate flex-1" title={path}>
                {path}
              </span>
              <button
                onClick={() => handleOpenSMB(path)}
                className="text-green-600 hover:text-green-900 flex-shrink-0"
                title="Open in SMB"
              >
                <FolderOpen className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <span className="text-sm text-gray-400">-</span>
          )
        },
      },
      {
        accessorKey: 'priority',
        header: ({ column }) => (
          <div className="flex flex-col gap-2 pb-2">
            <span>Priority</span>
            <Filter column={column} />
          </div>
        ),
        cell: ({ getValue }) => (
          <span className="text-sm text-gray-500">{getValue() as number}</span>
        ),
      },
      {
        accessorKey: 'created_at',
        header: 'Created At',
        cell: ({ getValue }) => (
          <span className="text-sm text-gray-500">
            {new Date(getValue() as string).toLocaleString()}
          </span>
        ),
      },
      {
        accessorKey: 'retry_count',
        header: 'Retries',
        cell: ({ getValue }) => (
          <div className="text-sm text-gray-500 text-center">{getValue() as number}</div>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => (
          <div className="flex gap-2 justify-center">
            {row.original.status === 'failed' && (
              <button
                onClick={() => handleRetry(row.original.id)}
                className="text-blue-600 hover:text-blue-900"
                title="Retry"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={() => handleDelete(row.original.id)}
              className="text-red-600 hover:text-red-900"
              title="Delete"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        ),
      },
    ],
    []
  )

  const table = useReactTable({
    data: tasks,
    columns,
    state: {
      pagination,
      columnFilters,
    },
    pageCount: totalPages,
    manualPagination: true,
    onPaginationChange: setPagination,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <div className="space-y-4">
      {/* Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden relative">
        {loading && (
          <div className="absolute inset-0 bg-white/60 z-10 flex items-center justify-center backdrop-blur-[1px]">
            <div className="flex flex-col items-center gap-2">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              <span className="text-sm text-gray-500">Loading...</span>
            </div>
          </div>
        )}
        
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              {table.getHeaderGroups().map(headerGroup => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map(header => (
                    <th
                      key={header.id}
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider align-top"
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {tasks.length === 0 && !loading ? (
                <tr>
                  <td colSpan={columns.length} className="px-6 py-12 text-center text-gray-500">
                    No tasks found
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map(row => (
                  <tr key={row.id} className="hover:bg-gray-50">
                    {row.getVisibleCells().map(cell => (
                      <td key={cell.id} className="px-6 py-4 whitespace-nowrap">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between bg-white">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-700">
              Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
            </span>
            <select
              value={table.getState().pagination.pageSize}
              onChange={e => {
                table.setPageSize(Number(e.target.value))
              }}
              className="ml-2 border-gray-300 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500"
            >
              {[10, 20, 30, 40, 50].map(pageSize => (
                <option key={pageSize} value={pageSize}>
                  Show {pageSize}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button
              className="p-2 border rounded hover:bg-gray-50 disabled:opacity-50"
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronsLeft className="w-4 h-4" />
            </button>
            <button
              className="p-2 border rounded hover:bg-gray-50 disabled:opacity-50"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              className="p-2 border rounded hover:bg-gray-50 disabled:opacity-50"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
            <button
              className="p-2 border rounded hover:bg-gray-50 disabled:opacity-50"
              onClick={() => table.setPageIndex(table.getPageCount() - 1)}
              disabled={!table.getCanNextPage()}
            >
              <ChevronsRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
