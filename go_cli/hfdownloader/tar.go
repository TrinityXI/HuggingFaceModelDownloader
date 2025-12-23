// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

package hfdownloader

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	// DefaultTarBufferSize 默认 I/O buffer 大小 (8MB，优化 SMB 网络传输)
	DefaultTarBufferSize = 8 * 1024 * 1024
	// DefaultTarCompressLevel 默认压缩级别 (1 = 最快)
	DefaultTarCompressLevel = 1
	// LocalModeThreshold 小于此大小使用 local 模式 (50GB)
	LocalModeThreshold = 50 * 1024 * 1024 * 1024
)

// TarMode tar 打包模式
type TarMode string

const (
	TarModeDefault TarMode = "default" // 传统模式：下载完成后在原地打包
	TarModeLocal   TarMode = "local"   // 本地缓存模式：下载到本地SSD，打包后复制到目标
	TarModeStream  TarMode = "stream"  // 流式模式：边下载边打包（不保留源文件）
	TarModeAuto    TarMode = "auto"    // 自动选择：< 50GB 用 local，>= 50GB 用 stream
)

// TarResult 打包结果
type TarResult struct {
	Files      []string // 生成的 tar 文件列表（可能多个分片）
	TotalSize  int64    // 原始文件总大小
	TarSize    int64    // tar 文件总大小
	FileCount  int      // 打包的文件数量
	SplitCount int      // 分片数量
	Mode       TarMode  // 使用的打包模式
}

// TarOptions 打包选项
type TarOptions struct {
	SourceDir      string                                  // 源目录
	OutputPath     string                                  // 输出路径（不含扩展名）
	SplitSize      int64                                   // 分片大小（字节），0 表示不分片
	SplitThreshold int64                                   // 超过此大小才分片（字节）
	Compress       bool                                    // 是否 gzip 压缩
	CompressLevel  int                                     // 压缩级别 1-9
	BufferSize     int                                     // I/O buffer 大小
	Progress       func(current, total int64, file string) // 进度回调
}

// getBufferSize 获取 buffer 大小，使用默认值如果未设置
func getBufferSize(cfg Settings) int {
	if cfg.TarBufferSize > 0 {
		return cfg.TarBufferSize
	}
	return DefaultTarBufferSize
}

// getCompressLevel 获取压缩级别，使用默认值如果未设置
func getCompressLevel(cfg Settings) int {
	if cfg.TarCompressLevel >= 1 && cfg.TarCompressLevel <= 9 {
		return cfg.TarCompressLevel
	}
	return DefaultTarCompressLevel
}

// TarDirectory 将目录打包为 tar（支持分片）
func TarDirectory(ctx context.Context, opts TarOptions) (*TarResult, error) {
	// 设置默认值
	if opts.BufferSize <= 0 {
		opts.BufferSize = DefaultTarBufferSize
	}
	if opts.CompressLevel <= 0 || opts.CompressLevel > 9 {
		opts.CompressLevel = DefaultTarCompressLevel
	}

	// 计算源目录总大小
	var totalSize int64
	var fileCount int
	err := filepath.Walk(opts.SourceDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		// Check for cancellation
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		if !info.IsDir() {
			totalSize += info.Size()
			fileCount++
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("scan source dir: %w", err)
	}

	result := &TarResult{
		TotalSize: totalSize,
		FileCount: fileCount,
		Mode:      TarModeDefault,
	}

	// 判断是否需要分片
	needSplit := opts.SplitSize > 0 && totalSize > opts.SplitThreshold

	if needSplit {
		return tarSplit(ctx, opts, result)
	}
	return tarSingle(ctx, opts, result)
}

// tarSingle 单文件打包（优化版：大 buffer + 可配置压缩级别）
func tarSingle(ctx context.Context, opts TarOptions, result *TarResult) (*TarResult, error) {
	ext := ".tar"
	if opts.Compress {
		ext = ".tar.gz"
	}
	outPath := opts.OutputPath + ext

	f, err := os.Create(outPath)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	// 使用 buffered writer 优化 SMB 写入
	bufWriter := NewBufferedWriter(f, opts.BufferSize)
	defer bufWriter.Flush()

	var tw *tar.Writer
	var gw *gzip.Writer
	if opts.Compress {
		var err error
		gw, err = gzip.NewWriterLevel(bufWriter, opts.CompressLevel)
		if err != nil {
			return nil, fmt.Errorf("create gzip writer: %w", err)
		}
		defer gw.Close()
		tw = tar.NewWriter(gw)
	} else {
		tw = tar.NewWriter(bufWriter)
	}
	defer tw.Close()

	// 创建读取 buffer
	readBuf := make([]byte, opts.BufferSize)

	var written int64
	err = filepath.Walk(opts.SourceDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		// Check for cancellation
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		// 构建相对路径
		rel, err := filepath.Rel(opts.SourceDir, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}

		header, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		header.Name = filepath.ToSlash(rel)

		if err := tw.WriteHeader(header); err != nil {
			return err
		}

		if !info.IsDir() {
			file, err := os.Open(path)
			if err != nil {
				return err
			}
			defer file.Close()

			// 使用大 buffer 复制，减少 syscall
			n, err := copyBuffer(tw, file, readBuf)
			if err != nil {
				return err
			}
			written += n

			if opts.Progress != nil {
				opts.Progress(written, result.TotalSize, rel)
			}
		}
		return nil
	})

	if err != nil {
		return nil, err
	}

	// Flush writers
	tw.Close()
	if gw != nil {
		gw.Close()
	}
	bufWriter.Flush()
	f.Sync()

	fi, _ := os.Stat(outPath)
	result.Files = []string{outPath}
	if fi != nil {
		result.TarSize = fi.Size()
	}
	result.SplitCount = 1
	return result, nil
}

// tarSplit 分片打包（优化版）
func tarSplit(ctx context.Context, opts TarOptions, result *TarResult) (*TarResult, error) {
	ext := ".tar"
	if opts.Compress {
		ext = ".tar.gz"
	}

	// 收集所有文件
	type fileEntry struct {
		path string
		rel  string
		size int64
		info os.FileInfo
	}
	var files []fileEntry

	err := filepath.Walk(opts.SourceDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		// Check for cancellation
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		if info.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(opts.SourceDir, path)
		files = append(files, fileEntry{
			path: path,
			rel:  rel,
			size: info.Size(),
			info: info,
		})
		return nil
	})
	if err != nil {
		return nil, err
	}

	// 分片打包
	var (
		partNum      int
		currentSize  int64
		tw           *tar.Writer
		currentFile  *os.File
		gw           *gzip.Writer
		bufWriter    *BufferedWriter
		outputFiles  []string
		totalWritten int64
		readBuf      = make([]byte, opts.BufferSize)
	)

	closeCurrentPart := func() {
		if tw != nil {
			tw.Close()
		}
		if gw != nil {
			gw.Close()
		}
		if bufWriter != nil {
			bufWriter.Flush()
		}
		if currentFile != nil {
			currentFile.Sync()
			currentFile.Close()
		}
	}

	startNewPart := func() error {
		// 关闭旧分片
		closeCurrentPart()

		partNum++
		partPath := fmt.Sprintf("%s.part%03d%s", opts.OutputPath, partNum, ext)
		outputFiles = append(outputFiles, partPath)

		var err error
		currentFile, err = os.Create(partPath)
		if err != nil {
			return err
		}

		bufWriter = NewBufferedWriter(currentFile, opts.BufferSize)

		if opts.Compress {
			gw, err = gzip.NewWriterLevel(bufWriter, opts.CompressLevel)
			if err != nil {
				return err
			}
			tw = tar.NewWriter(gw)
		} else {
			gw = nil
			tw = tar.NewWriter(bufWriter)
		}
		currentSize = 0
		return nil
	}

	// 开始第一个分片
	if err := startNewPart(); err != nil {
		return nil, err
	}

	for _, fe := range files {
		// Check for cancellation
		select {
		case <-ctx.Done():
			closeCurrentPart()
			return nil, ctx.Err()
		default:
		}

		// 检查是否需要新分片（当前分片非空且加入此文件会超限）
		if currentSize > 0 && currentSize+fe.size > opts.SplitSize {
			if err := startNewPart(); err != nil {
				return nil, err
			}
		}

		header, err := tar.FileInfoHeader(fe.info, "")
		if err != nil {
			closeCurrentPart()
			return nil, err
		}
		header.Name = filepath.ToSlash(fe.rel)

		if err := tw.WriteHeader(header); err != nil {
			closeCurrentPart()
			return nil, err
		}

		file, err := os.Open(fe.path)
		if err != nil {
			closeCurrentPart()
			return nil, err
		}

		n, err := copyBuffer(tw, file, readBuf)
		file.Close()
		if err != nil {
			closeCurrentPart()
			return nil, err
		}

		currentSize += n
		totalWritten += n

		if opts.Progress != nil {
			opts.Progress(totalWritten, result.TotalSize, fe.rel)
		}
	}

	// 关闭最后一个分片
	closeCurrentPart()

	// 统计输出大小
	var tarTotal int64
	for _, p := range outputFiles {
		if fi, err := os.Stat(p); err == nil {
			tarTotal += fi.Size()
		}
	}

	result.Files = outputFiles
	result.TarSize = tarTotal
	result.SplitCount = len(outputFiles)
	return result, nil
}

// BufferedWriter 带缓冲的 writer，优化 SMB 写入性能
type BufferedWriter struct {
	w      io.Writer
	buf    []byte
	n      int
	size   int
}

// NewBufferedWriter 创建新的 buffered writer
func NewBufferedWriter(w io.Writer, size int) *BufferedWriter {
	return &BufferedWriter{
		w:    w,
		buf:  make([]byte, size),
		size: size,
	}
}

// Write 实现 io.Writer
func (b *BufferedWriter) Write(p []byte) (n int, err error) {
	for len(p) > 0 {
		// 如果 buffer 满了，flush
		if b.n >= b.size {
			if err := b.Flush(); err != nil {
				return n, err
			}
		}
		// 复制数据到 buffer
		copied := copy(b.buf[b.n:], p)
		b.n += copied
		n += copied
		p = p[copied:]
	}
	return n, nil
}

// Flush 刷新 buffer 到底层 writer
func (b *BufferedWriter) Flush() error {
	if b.n == 0 {
		return nil
	}
	_, err := b.w.Write(b.buf[:b.n])
	b.n = 0
	return err
}

// copyBuffer 使用指定 buffer 复制数据
func copyBuffer(dst io.Writer, src io.Reader, buf []byte) (int64, error) {
	var written int64
	for {
		nr, rerr := src.Read(buf)
		if nr > 0 {
			nw, werr := dst.Write(buf[:nr])
			if nw > 0 {
				written += int64(nw)
			}
			if werr != nil {
				return written, werr
			}
			if nr != nw {
				return written, io.ErrShortWrite
			}
		}
		if rerr != nil {
			if rerr == io.EOF {
				return written, nil
			}
			return written, rerr
		}
	}
}

// CleanupSource 删除源文件夹
func CleanupSource(dir string) error {
	return os.RemoveAll(dir)
}

// StreamModeThreshold 超过此大小自动使用 stream 模式 (100GB)
const StreamModeThreshold = 100 * 1024 * 1024 * 1024

// DownloadAndTar 下载并打包（支持多种模式）
func DownloadAndTar(ctx context.Context, job Job, cfg Settings, progress ProgressFunc) (*TarResult, error) {
	emit := func(ev ProgressEvent) {
		if progress != nil {
			if ev.Time.IsZero() {
				ev.Time = time.Now()
			}
			if ev.Repo == "" {
				ev.Repo = job.Repo
			}
			if ev.Revision == "" {
				ev.Revision = job.Revision
			}
			progress(ev)
		}
	}

	// 确定 tar 模式
	mode := TarMode(cfg.TarMode)
	
	// 如果是 auto 模式或未指定，需要先扫描确定大小
	if (mode == "" || mode == TarModeAuto) && cfg.TarAfterDownload {
		emit(ProgressEvent{Event: "info", Message: "auto mode: scanning to determine optimal tar mode..."})
		
		// 先扫描获取文件列表和总大小
		plan, err := PlanRepo(ctx, job, cfg)
		if err != nil {
			// Tree API 失败时，回退到 default 模式
			emit(ProgressEvent{
				Event:   "warning",
				Message: fmt.Sprintf("auto mode: failed to scan repo (%v), falling back to default mode", err),
			})
			mode = TarModeDefault
		} else {
			var totalSize int64
			for _, item := range plan.Items {
				totalSize += item.Size
			}
			
			// 根据大小选择模式
			if totalSize >= StreamModeThreshold {
				mode = TarModeStream
				emit(ProgressEvent{
					Event:   "info",
					Message: fmt.Sprintf("auto mode: total size %s >= 100GB, using stream mode", formatBytes(totalSize)),
				})
			} else {
				mode = TarModeDefault
				emit(ProgressEvent{
					Event:   "info",
					Message: fmt.Sprintf("auto mode: total size %s < 100GB, using default mode", formatBytes(totalSize)),
				})
			}
		}
	} else if mode == "" {
		mode = TarModeDefault
	}

	// 如果是流式模式，使用专门的流式下载+打包
	if mode == TarModeStream && cfg.TarAfterDownload {
		return downloadAndTarStream(ctx, job, cfg, progress)
	}

	// 如果是本地缓存模式
	if mode == TarModeLocal && cfg.TarAfterDownload {
		return downloadAndTarLocal(ctx, job, cfg, progress)
	}

	// 传统模式：先下载，再打包
	if err := Download(ctx, job, cfg, progress); err != nil {
		return nil, err
	}

	// 如果不需要打包，直接返回
	if !cfg.TarAfterDownload {
		return nil, nil
	}

	emit(ProgressEvent{Event: "tar_start", Message: "starting tar compression"})

	// 解析分片参数
	splitSize, _ := parseSizeString(cfg.TarSplitSize, 50<<30)
	splitThreshold, _ := parseSizeString(cfg.TarSplitThreshold, 100<<30)

	// 确定输出路径
	sourceDir := destinationBase(job, cfg)
	outputDir := cfg.TarOutputDir
	if outputDir == "" {
		outputDir = cfg.OutputDir
	}

	// 确保输出目录存在
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, fmt.Errorf("create tar output dir: %w", err)
	}

	// 输出文件名
	baseName := strings.ReplaceAll(job.Repo, "/", "_")
	if job.Revision != "" && job.Revision != "main" {
		baseName += "_" + job.Revision
	}
	outputPath := filepath.Join(outputDir, baseName)

	// 打包
	opts := TarOptions{
		SourceDir:      sourceDir,
		OutputPath:     outputPath,
		SplitSize:      splitSize,
		SplitThreshold: splitThreshold,
		Compress:       cfg.TarCompress,
		CompressLevel:  getCompressLevel(cfg),
		BufferSize:     getBufferSize(cfg),
		Progress: func(current, total int64, file string) {
			emit(ProgressEvent{
				Event:   "tar_progress",
				Path:    file,
				Bytes:   current,
				Total:   total,
				Message: fmt.Sprintf("packing: %s", file),
			})
		},
	}

	result, err := TarDirectory(ctx, opts)
	if err != nil {
		return nil, fmt.Errorf("tar failed: %w", err)
	}

	// 通知完成
	msg := fmt.Sprintf("tar complete: %d files, %d parts, total size: %s",
		result.FileCount, result.SplitCount, formatBytes(result.TarSize))
	emit(ProgressEvent{
		Event:   "tar_done",
		Message: msg,
	})

	// 可选：删除源文件
	if cfg.TarDeleteSource {
		emit(ProgressEvent{Event: "info", Message: "cleaning up source files..."})
		if err := CleanupSource(sourceDir); err != nil {
			emit(ProgressEvent{
				Event:   "warning",
				Level:   "warn",
				Message: fmt.Sprintf("cleanup failed: %v", err),
			})
		} else {
			emit(ProgressEvent{Event: "info", Message: "source files cleaned up"})
		}
	}

	return result, nil
}

// downloadAndTarLocal 本地缓存模式：下载到本地 SSD，打包后复制到目标
func downloadAndTarLocal(ctx context.Context, job Job, cfg Settings, progress ProgressFunc) (*TarResult, error) {
	emit := func(ev ProgressEvent) {
		if progress != nil {
			if ev.Time.IsZero() {
				ev.Time = time.Now()
			}
			if ev.Repo == "" {
				ev.Repo = job.Repo
			}
			if ev.Revision == "" {
				ev.Revision = job.Revision
			}
			progress(ev)
		}
	}

	// 确定本地缓存目录
	localCacheDir := cfg.TarLocalCacheDir
	if localCacheDir == "" {
		localCacheDir = os.TempDir()
	}

	// 创建临时目录
	tempDir, err := os.MkdirTemp(localCacheDir, "hfdownloader-")
	if err != nil {
		return nil, fmt.Errorf("create temp dir: %w", err)
	}
	defer os.RemoveAll(tempDir) // 清理临时目录

	emit(ProgressEvent{
		Event:   "info",
		Message: fmt.Sprintf("using local cache mode, temp dir: %s", tempDir),
	})

	// 1. 下载到本地临时目录
	localCfg := cfg
	localCfg.OutputDir = tempDir
	localCfg.TarAfterDownload = false // 先不打包

	if err := Download(ctx, job, localCfg, progress); err != nil {
		return nil, err
	}

	// 2. 在本地打包
	emit(ProgressEvent{Event: "tar_start", Message: "packing on local disk (fast)"})

	splitSize, _ := parseSizeString(cfg.TarSplitSize, 50<<30)
	splitThreshold, _ := parseSizeString(cfg.TarSplitThreshold, 100<<30)

	sourceDir := filepath.Join(tempDir, job.Repo)
	
	// 临时 tar 文件也在本地
	baseName := strings.ReplaceAll(job.Repo, "/", "_")
	if job.Revision != "" && job.Revision != "main" {
		baseName += "_" + job.Revision
	}
	localTarPath := filepath.Join(tempDir, baseName)

	opts := TarOptions{
		SourceDir:      sourceDir,
		OutputPath:     localTarPath,
		SplitSize:      splitSize,
		SplitThreshold: splitThreshold,
		Compress:       cfg.TarCompress,
		CompressLevel:  getCompressLevel(cfg),
		BufferSize:     getBufferSize(cfg),
		Progress: func(current, total int64, file string) {
			emit(ProgressEvent{
				Event:   "tar_progress",
				Path:    file,
				Bytes:   current,
				Total:   total,
				Message: fmt.Sprintf("packing: %s", file),
			})
		},
	}

	result, err := TarDirectory(ctx, opts)
	if err != nil {
		return nil, fmt.Errorf("tar failed: %w", err)
	}
	result.Mode = TarModeLocal

	// 3. 复制 tar 文件到目标 SMB 目录
	emit(ProgressEvent{Event: "info", Message: "copying tar files to target..."})

	outputDir := cfg.TarOutputDir
	if outputDir == "" {
		outputDir = cfg.OutputDir
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, fmt.Errorf("create output dir: %w", err)
	}

	var finalFiles []string
	var totalCopied int64
	copyBuf := make([]byte, getBufferSize(cfg))

	for i, localFile := range result.Files {
		targetFile := filepath.Join(outputDir, filepath.Base(localFile))
		
		if err := copyFileWithBuffer(ctx, localFile, targetFile, copyBuf, func(copied, total int64) {
			emit(ProgressEvent{
				Event:   "copy_progress",
				Path:    filepath.Base(localFile),
				Bytes:   totalCopied + copied,
				Total:   result.TarSize,
				Message: fmt.Sprintf("copying %d/%d: %s", i+1, len(result.Files), filepath.Base(localFile)),
			})
		}); err != nil {
			return nil, fmt.Errorf("copy tar file: %w", err)
		}

		fi, _ := os.Stat(targetFile)
		if fi != nil {
			totalCopied += fi.Size()
		}
		finalFiles = append(finalFiles, targetFile)
	}

	result.Files = finalFiles

	msg := fmt.Sprintf("tar complete (local mode): %d files, %d parts, size: %s",
		result.FileCount, result.SplitCount, formatBytes(result.TarSize))
	emit(ProgressEvent{
		Event:   "tar_done",
		Message: msg,
	})

	return result, nil
}

// downloadAndTarStream 流式模式：边下载边打包
func downloadAndTarStream(ctx context.Context, job Job, cfg Settings, progress ProgressFunc) (*TarResult, error) {
	emit := func(ev ProgressEvent) {
		if progress != nil {
			if ev.Time.IsZero() {
				ev.Time = time.Now()
			}
			if ev.Repo == "" {
				ev.Repo = job.Repo
			}
			if ev.Revision == "" {
				ev.Revision = job.Revision
			}
			progress(ev)
		}
	}

	emit(ProgressEvent{Event: "info", Message: "using stream mode (download directly to tar)"})

	// 1. 先扫描获取文件列表
	emit(ProgressEvent{Event: "scan_start", Message: "scanning repo for stream tar"})
	
	plan, err := PlanRepo(ctx, job, cfg)
	if err != nil {
		return nil, fmt.Errorf("plan repo: %w", err)
	}

	// 计算总大小
	var totalSize int64
	for _, item := range plan.Items {
		totalSize += item.Size
	}

	emit(ProgressEvent{
		Event:   "scan_complete",
		Message: fmt.Sprintf("found %d files, total: %s", len(plan.Items), formatBytes(totalSize)),
		Bytes:   int64(len(plan.Items)),
		Total:   totalSize,
	})

	// 2. 创建 tar 文件
	outputDir := cfg.TarOutputDir
	if outputDir == "" {
		outputDir = cfg.OutputDir
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, fmt.Errorf("create output dir: %w", err)
	}

	baseName := strings.ReplaceAll(job.Repo, "/", "_")
	if job.Revision != "" && job.Revision != "main" {
		baseName += "_" + job.Revision
	}

	ext := ".tar"
	if cfg.TarCompress {
		ext = ".tar.gz"
	}
	tarPath := filepath.Join(outputDir, baseName+ext)

	f, err := os.Create(tarPath)
	if err != nil {
		return nil, fmt.Errorf("create tar file: %w", err)
	}
	defer f.Close()

	bufWriter := NewBufferedWriter(f, getBufferSize(cfg))
	defer bufWriter.Flush()

	var tw *tar.Writer
	var gw *gzip.Writer

	if cfg.TarCompress {
		gw, err = gzip.NewWriterLevel(bufWriter, getCompressLevel(cfg))
		if err != nil {
			return nil, fmt.Errorf("create gzip writer: %w", err)
		}
		defer gw.Close()
		tw = tar.NewWriter(gw)
	} else {
		tw = tar.NewWriter(bufWriter)
	}
	defer tw.Close()

	// 3. 流式下载并写入 tar
	httpc := buildHTTPClient()
	var written int64
	var fileCount int

	emit(ProgressEvent{Event: "tar_start", Message: "streaming download to tar"})

	for _, item := range plan.Items {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		// 下载文件到内存/流并写入 tar
		if err := streamFileToTar(ctx, httpc, cfg.Token, item, tw, func(bytes int64) {
			emit(ProgressEvent{
				Event:   "tar_progress",
				Path:    item.RelativePath,
				Bytes:   written + bytes,
				Total:   totalSize,
				Message: fmt.Sprintf("streaming: %s", item.RelativePath),
			})
		}); err != nil {
			return nil, fmt.Errorf("stream file %s: %w", item.RelativePath, err)
		}

		written += item.Size
		fileCount++

		emit(ProgressEvent{
			Event:   "file_done",
			Path:    item.RelativePath,
			Bytes:   written,
			Total:   totalSize,
			Message: fmt.Sprintf("streamed %d/%d files", fileCount, len(plan.Items)),
		})
	}

	// 关闭 writers
	tw.Close()
	if gw != nil {
		gw.Close()
	}
	bufWriter.Flush()
	f.Sync()

	fi, _ := os.Stat(tarPath)
	tarSize := int64(0)
	if fi != nil {
		tarSize = fi.Size()
	}

	result := &TarResult{
		Files:      []string{tarPath},
		TotalSize:  totalSize,
		TarSize:    tarSize,
		FileCount:  fileCount,
		SplitCount: 1,
		Mode:       TarModeStream,
	}

	msg := fmt.Sprintf("stream tar complete: %d files, size: %s (compressed: %s)",
		fileCount, formatBytes(totalSize), formatBytes(tarSize))
	emit(ProgressEvent{
		Event:   "tar_done",
		Message: msg,
	})

	return result, nil
}

// streamFileToTar 流式下载文件并直接写入 tar
func streamFileToTar(ctx context.Context, httpc *http.Client, token string, item PlanItem, tw *tar.Writer, onProgress func(int64)) error {
	// 创建 HTTP 请求
	req, err := http.NewRequestWithContext(ctx, "GET", item.URL, nil)
	if err != nil {
		return err
	}
	addAuth(req, token)

	resp, err := httpc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return fmt.Errorf("bad status: %s", resp.Status)
	}

	// 写入 tar header
	header := &tar.Header{
		Name:    item.RelativePath,
		Size:    item.Size,
		Mode:    0644,
		ModTime: time.Now(),
	}
	if err := tw.WriteHeader(header); err != nil {
		return err
	}

	// 流式写入内容
	buf := make([]byte, DefaultTarBufferSize)
	var written int64
	lastProgress := time.Now()
	progressInterval := 200 * time.Millisecond // 更频繁的进度更新

	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			_, werr := tw.Write(buf[:n])
			if werr != nil {
				return werr
			}
			written += int64(n)

			// 限制进度回调频率
			if time.Since(lastProgress) > progressInterval {
				if onProgress != nil {
					onProgress(written)
				}
				lastProgress = time.Now()
			}
		}
		if rerr != nil {
			if rerr == io.EOF {
				// 文件完成时发送最终进度更新
				if onProgress != nil {
					onProgress(written)
				}
				return nil
			}
			return rerr
		}
	}
}

// copyFileWithBuffer 使用大 buffer 复制文件
func copyFileWithBuffer(ctx context.Context, src, dst string, buf []byte, onProgress func(copied, total int64)) error {
	srcFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer srcFile.Close()

	fi, err := srcFile.Stat()
	if err != nil {
		return err
	}
	total := fi.Size()

	dstFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer dstFile.Close()

	var copied int64
	lastProgress := time.Now()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		n, rerr := srcFile.Read(buf)
		if n > 0 {
			_, werr := dstFile.Write(buf[:n])
			if werr != nil {
				return werr
			}
			copied += int64(n)

			if time.Since(lastProgress) > 500*time.Millisecond {
				if onProgress != nil {
					onProgress(copied, total)
				}
				lastProgress = time.Now()
			}
		}
		if rerr != nil {
			if rerr == io.EOF {
				return dstFile.Sync()
			}
			return rerr
		}
	}
}

// formatBytes formats bytes to human readable string
func formatBytes(b int64) string {
	const unit = 1024
	if b < unit {
		return fmt.Sprintf("%d B", b)
	}
	div, exp := int64(unit), 0
	for n := b / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.2f %ciB", float64(b)/float64(div), "KMGTPE"[exp])
}
