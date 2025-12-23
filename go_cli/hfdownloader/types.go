package hfdownloader

import "time"

type Job struct {
	Repo               string
	IsDataset          bool
	Revision           string
	Filters            []string
	AppendFilterSubdir bool
}
type Settings struct {
	OutputDir          string
	Concurrency        int
	MaxActiveDownloads int
	MultipartThreshold string
	Verify             string
	Retries            int
	BackoffInitial     string
	BackoffMax         string
	Token              string
	// Endpoint is the base URL for HuggingFace API (default: https://huggingface.co)
	Endpoint string
	// MirrorEndpoint is the fallback mirror URL (e.g., https://hf-mirror.com)
	MirrorEndpoint string
	// UseMirrorOnFailure enables automatic fallback to mirror on primary failure
	UseMirrorOnFailure bool
	// UseRecursiveScan enables recursive tree API to reduce API calls for repos with many directories
	// When enabled, uses ?recursive=true parameter which fetches all files in one API call per directory
	UseRecursiveScan bool
	// RecursiveDepth controls the depth of directories to fetch with recursive scan (0 = unlimited)
	RecursiveDepth int
	// ScanRateLimit limits API calls per second during scanning (0 = no limit)
	ScanRateLimit float64

	// Tar compression options
	TarAfterDownload  bool   // 下载完成后是否打包为 tar
	TarCompress       bool   // 是否使用 gzip 压缩（生成 .tar.gz）
	TarSplitSize      string // 分片大小，如 "50GiB"，为空则不分片
	TarSplitThreshold string // 超过此大小才分片，如 "100GiB"
	TarOutputDir      string // tar 输出目录，为空则与 OutputDir 相同
	TarDeleteSource   bool   // 打包后删除源文件
	TarMode           string // tar 模式: "local" (本地缓存+tar), "stream" (流式tar), "default" (传统模式)
	TarLocalCacheDir  string // 本地缓存目录（用于 local 模式）
	TarBufferSize     int    // I/O buffer 大小（字节），默认 8MB
	TarCompressLevel  int    // gzip 压缩级别 1-9，默认 1（最快）
}

type ProgressEvent struct {
	Time     time.Time `json:"time"`
	Level    string    `json:"level,omitempty"`
	Event    string    `json:"event"`
	Repo     string    `json:"repo,omitempty"`
	Revision string    `json:"revision,omitempty"`
	Path     string    `json:"path,omitempty"`
	Bytes    int64     `json:"bytes,omitempty"`
	Total    int64     `json:"total,omitempty"`
	Attempt  int       `json:"attempt,omitempty"`
	Message  string    `json:"message,omitempty"`
}

type ProgressFunc func(ProgressEvent)
