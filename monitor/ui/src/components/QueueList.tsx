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
        className="w-full px-2 py-1 text-xs font-normal border border-surface-border rounded-lg bg-surface-raised focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/40 transition-all"
        onClick={e => e.stopPropagation()}
      />
    )
  }

  if (id === 'status') {
    return (
      <select
        value={(columnFilterValue as string) ?? ''}
        onChange={e => column.setFilterValue(e.target.value)}
        className="w-full px-2 py-1 text-xs font-normal border border-surface-border rounded-lg bg-surface-raised focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/40 transition-all"
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
        className="w-full px-2 py-1 text-xs font-normal border border-surface-border rounded-lg bg-surface-raised focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/40 transition-all"
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
  const [rowSelection, setRowSelection] = useState({})
  
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

  const handleBatchDelete = async () => {
    const selectedRows = table.getSelectedRowModel().rows
    const taskIds = selectedRows.map(r => r.original.id)
    if (!taskIds.length) return
    
    if (!confirm(`Are you sure you want to delete ${taskIds.length} tasks?`)) return

    try {
      await axios.post(`${API_BASE_URL}/queue/batch-delete`, { task_ids: taskIds })
      setRowSelection({})
      fetchTasks()
    } catch (error) {
      console.error('Failed to batch delete tasks:', error)
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
    const configs: Record<string, { color: string; dot: string; icon: any; label: string }> = {
      pending: { color: 'bg-amber-50 text-amber-700 ring-amber-200/60', dot: 'bg-amber-500', icon: Clock, label: 'Pending' },
      downloading: { color: 'bg-accent-light text-accent ring-accent/15', dot: 'bg-accent', icon: Download, label: 'Downloading' },
      completed: { color: 'bg-emerald-50 text-emerald-700 ring-emerald-200/60', dot: 'bg-emerald-500', icon: CheckCircle, label: 'Completed' },
      failed: { color: 'bg-rose-50 text-rose-700 ring-rose-200/60', dot: 'bg-rose-500', icon: XCircle, label: 'Failed' },
    }
    
    const config = configs[status] || configs.pending
    
    return (
      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium ring-1 ${config.color}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${config.dot} ${status === 'downloading' ? 'animate-pulse' : ''}`} />
        {config.label}
      </span>
    )
  }

  const columns = useMemo<ColumnDef<Task>[]>(
    () => [
      {
        id: 'select',
        header: ({ table }) => (
          <div className="flex items-center justify-center h-full">
            <input
              type="checkbox"
              className="w-4 h-4 rounded border-surface-border text-accent focus:ring-accent/30"
              checked={table.getIsAllPageRowsSelected()}
              onChange={table.getToggleAllPageRowsSelectedHandler()}
            />
          </div>
        ),
        cell: ({ row }) => (
          <div className="flex items-center justify-center">
            <input
              type="checkbox"
              className="w-4 h-4 rounded border-surface-border text-accent focus:ring-accent/30"
              checked={row.getIsSelected()}
              onChange={row.getToggleSelectedHandler()}
            />
          </div>
        ),
      },
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
              <div className="text-sm font-medium text-ink truncate" title={row.original.dataset_id}>
                {row.original.dataset_id}
              </div>
              {row.original.last_error && (
                <div className="text-xs text-rose-600 mt-1 truncate" title={row.original.last_error}>
                  {row.original.last_error}
                </div>
              )}
            </div>
            <a
              href={`https://huggingface.co/datasets/${row.original.dataset_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="btn text-ink-tertiary hover:text-accent flex-shrink-0 p-1 rounded-md hover:bg-accent-light transition-colors"
              title="View on HuggingFace"
            >
              <ExternalLink className="w-3.5 h-3.5" />
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
              <div className="min-w-[200px] space-y-1.5">
              {/* Progress Status Badge */}
              <div className="flex items-center justify-between text-xs">
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-xs font-medium ${
                  isScanning 
                    ? 'bg-violet-50 text-violet-700 ring-1 ring-violet-200/60' 
                    : 'bg-accent-light text-accent ring-1 ring-accent/15'
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
                <span className="font-medium text-accent tabular-nums">
                  {isScanning ? `${progress.total_files} files found` : `${progress.percentage.toFixed(1)}%`}
                </span>
              </div>
              {/* File Progress */}
              <div className="flex items-center justify-between text-xs text-ink-secondary">
                <span className="tabular-nums">
                  {progress.completed_files}/{progress.total_files} files
                </span>
              </div>
              <div className="w-full bg-surface-sunken rounded-full h-1.5 overflow-hidden">
                <div 
                  className={`h-1.5 rounded-full transition-all duration-500 ease-out ${
                    isScanning ? 'bg-violet-500 animate-pulse' : 'bg-accent'
                  }`}
                  style={{ width: isScanning ? '100%' : `${Math.min(100, progress.percentage)}%` }}
                />
              </div>
              {!isScanning && (
              <div className="flex items-center justify-between text-xs text-ink-tertiary">
                <span className="font-mono tabular-nums">
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
            <div className="flex items-center gap-2 text-sm text-ink-secondary min-w-0">
              <Folder className="w-3.5 h-3.5 text-ink-tertiary flex-shrink-0" />
              <span className="truncate flex-1 font-mono text-xs" title={path}>
                {path}
              </span>
              <button
                onClick={() => handleOpenSMB(path)}
                className="btn text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 flex-shrink-0 p-1 rounded-md transition-colors"
                title="Open in SMB"
              >
                <FolderOpen className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <span className="text-sm text-ink-tertiary">—</span>
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
          <span className="text-sm text-ink-secondary tabular-nums">{getValue() as number}</span>
        ),
      },
      {
        accessorKey: 'created_at',
        header: 'Created At',
        cell: ({ getValue }) => (
          <span className="text-sm text-ink-secondary tabular-nums">
            {new Date(getValue() as string).toLocaleString()}
          </span>
        ),
      },
      {
        accessorKey: 'retry_count',
        header: 'Retries',
        cell: ({ getValue }) => (
          <div className="text-sm text-ink-secondary text-center tabular-nums">{getValue() as number}</div>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => (
          <div className="flex gap-1 justify-center">
            {row.original.status === 'failed' && (
              <button
                onClick={() => handleRetry(row.original.id)}
                className="btn p-1.5 text-accent hover:bg-accent-light rounded-lg transition-colors"
                title="Retry"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={() => handleDelete(row.original.id)}
              className="btn p-1.5 text-ink-tertiary hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
              title="Delete"
            >
              <Trash2 className="w-3.5 h-3.5" />
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
      rowSelection,
    },
    pageCount: totalPages,
    manualPagination: true,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onPaginationChange: setPagination,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      {Object.keys(rowSelection).length > 0 && (
        <div className="flex items-center gap-4 p-3 bg-surface rounded-2xl shadow-soft ring-1 ring-surface-border/50">
          <span className="text-sm font-medium text-ink-secondary">
            {Object.keys(rowSelection).length} task(s) selected
          </span>
          <button
            onClick={handleBatchDelete}
            className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-white bg-rose-500 hover:bg-rose-600 rounded-lg shadow-sm transition-all focus:ring-2 focus:ring-rose-500/30"
          >
            <Trash2 className="w-4 h-4" />
            Batch Delete
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-surface rounded-2xl shadow-soft ring-1 ring-surface-border/50 overflow-hidden relative">
        {loading && (
          <div className="absolute inset-0 bg-surface/70 z-10 flex items-center justify-center backdrop-blur-[2px]">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-accent/10 flex items-center justify-center">
                <div className="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
              </div>
              <span className="text-sm text-ink-secondary">Loading tasks...</span>
            </div>
          </div>
        )}
        
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-surface-border">
            <thead className="bg-surface-sunken/50">
              {table.getHeaderGroups().map(headerGroup => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map(header => (
                    <th
                      key={header.id}
                      className="px-5 py-3 text-left text-[11px] font-semibold text-ink-tertiary uppercase tracking-wider align-top"
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
            <tbody className="bg-surface divide-y divide-surface-border/70">
              {tasks.length === 0 && !loading ? (
                <tr>
                  <td colSpan={columns.length} className="px-6 py-16 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-12 h-12 rounded-2xl bg-surface-sunken flex items-center justify-center">
                        <Download className="w-5 h-5 text-ink-tertiary" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-ink-secondary">No tasks found</p>
                        <p className="text-xs text-ink-tertiary mt-1">Tasks matching your filters will appear here</p>
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map(row => (
                  <tr key={row.id} className="hover:bg-surface-raised/80 transition-colors duration-100">
                    {row.getVisibleCells().map(cell => (
                      <td key={cell.id} className="px-5 py-3.5 whitespace-nowrap">
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
        <div className="px-5 py-3.5 border-t border-surface-border/70 flex items-center justify-between bg-surface-raised/50">
          <div className="flex items-center gap-2">
            <span className="text-sm text-ink-secondary tabular-nums">
              Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
            </span>
            <select
              value={table.getState().pagination.pageSize}
              onChange={e => {
                table.setPageSize(Number(e.target.value))
              }}
              className="ml-2 border-surface-border rounded-lg text-sm bg-surface focus:ring-2 focus:ring-accent/30 focus:border-accent/40 transition-all"
            >
              {[10, 20, 30, 40, 50].map(pageSize => (
                <option key={pageSize} value={pageSize}>
                  Show {pageSize}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-1">
            <button
              className="btn p-2 border border-surface-border rounded-lg hover:bg-surface-sunken disabled:opacity-40 disabled:cursor-not-allowed text-ink-secondary"
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronsLeft className="w-4 h-4" />
            </button>
            <button
              className="btn p-2 border border-surface-border rounded-lg hover:bg-surface-sunken disabled:opacity-40 disabled:cursor-not-allowed text-ink-secondary"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              className="btn p-2 border border-surface-border rounded-lg hover:bg-surface-sunken disabled:opacity-40 disabled:cursor-not-allowed text-ink-secondary"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
            <button
              className="btn p-2 border border-surface-border rounded-lg hover:bg-surface-sunken disabled:opacity-40 disabled:cursor-not-allowed text-ink-secondary"
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
