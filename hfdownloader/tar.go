// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

package hfdownloader

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// TarResult 打包结果
type TarResult struct {
	Files      []string // 生成的 tar 文件列表（可能多个分片）
	TotalSize  int64    // 原始文件总大小
	TarSize    int64    // tar 文件总大小
	FileCount  int      // 打包的文件数量
	SplitCount int      // 分片数量
}

// TarOptions 打包选项
type TarOptions struct {
	SourceDir      string                                  // 源目录
	OutputPath     string                                  // 输出路径（不含扩展名）
	SplitSize      int64                                   // 分片大小（字节），0 表示不分片
	SplitThreshold int64                                   // 超过此大小才分片（字节）
	Compress       bool                                    // 是否 gzip 压缩
	Progress       func(current, total int64, file string) // 进度回调
}

// TarDirectory 将目录打包为 tar（支持分片）
func TarDirectory(ctx context.Context, opts TarOptions) (*TarResult, error) {
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
	}

	// 判断是否需要分片
	needSplit := opts.SplitSize > 0 && totalSize > opts.SplitThreshold

	if needSplit {
		return tarSplit(ctx, opts, result)
	}
	return tarSingle(ctx, opts, result)
}

// tarSingle 单文件打包
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

	var tw *tar.Writer
	var gw *gzip.Writer
	if opts.Compress {
		gw = gzip.NewWriter(f)
		defer gw.Close()
		tw = tar.NewWriter(gw)
	} else {
		tw = tar.NewWriter(f)
	}
	defer tw.Close()

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

			n, err := io.Copy(tw, file)
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
	f.Sync()

	fi, _ := os.Stat(outPath)
	result.Files = []string{outPath}
	if fi != nil {
		result.TarSize = fi.Size()
	}
	result.SplitCount = 1
	return result, nil
}

// tarSplit 分片打包
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
		outputFiles  []string
		totalWritten int64
	)

	closeCurrentPart := func() {
		if tw != nil {
			tw.Close()
		}
		if gw != nil {
			gw.Close()
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

		if opts.Compress {
			gw = gzip.NewWriter(currentFile)
			tw = tar.NewWriter(gw)
		} else {
			gw = nil
			tw = tar.NewWriter(currentFile)
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

		n, err := io.Copy(tw, file)
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

// CleanupSource 删除源文件夹
func CleanupSource(dir string) error {
	return os.RemoveAll(dir)
}

// DownloadAndTar 下载并打包（便捷方法）
func DownloadAndTar(ctx context.Context, job Job, cfg Settings, progress ProgressFunc) (*TarResult, error) {
	// 1. 先下载
	if err := Download(ctx, job, cfg, progress); err != nil {
		return nil, err
	}

	// 2. 如果不需要打包，直接返回
	if !cfg.TarAfterDownload {
		return nil, nil
	}

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

	emit(ProgressEvent{Event: "tar_start", Message: "starting tar compression"})

	// 3. 解析分片参数
	splitSize, _ := parseSizeString(cfg.TarSplitSize, 50<<30)            // 默认 50GiB
	splitThreshold, _ := parseSizeString(cfg.TarSplitThreshold, 100<<30) // 默认 100GiB

	// 4. 确定输出路径
	sourceDir := destinationBase(job, cfg)
	outputDir := cfg.TarOutputDir
	if outputDir == "" {
		outputDir = cfg.OutputDir
	}

	// 确保输出目录存在
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, fmt.Errorf("create tar output dir: %w", err)
	}

	// 输出文件名：repo 名称（替换 / 为 _）
	baseName := strings.ReplaceAll(job.Repo, "/", "_")
	if job.Revision != "" && job.Revision != "main" {
		baseName += "_" + job.Revision
	}
	outputPath := filepath.Join(outputDir, baseName)

	// 5. 打包
	opts := TarOptions{
		SourceDir:      sourceDir,
		OutputPath:     outputPath,
		SplitSize:      splitSize,
		SplitThreshold: splitThreshold,
		Compress:       cfg.TarCompress,
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

	// 6. 通知完成
	msg := fmt.Sprintf("tar complete: %d files, %d parts, total size: %s",
		result.FileCount, result.SplitCount, formatBytes(result.TarSize))
	emit(ProgressEvent{
		Event:   "tar_done",
		Message: msg,
	})

	// 7. 可选：删除源文件
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
