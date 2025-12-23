// Copyright 2025
// SPDX-License-Identifier: Apache-2.0

package hfdownloader

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestTarDirectorySingle(t *testing.T) {
	// Create temp directory with test files
	tempDir := t.TempDir()
	sourceDir := filepath.Join(tempDir, "source")
	os.MkdirAll(filepath.Join(sourceDir, "subdir"), 0755)
	
	// Create test files
	os.WriteFile(filepath.Join(sourceDir, "file1.txt"), []byte("content of file 1"), 0644)
	os.WriteFile(filepath.Join(sourceDir, "file2.txt"), []byte("content of file 2, longer"), 0644)
	os.WriteFile(filepath.Join(sourceDir, "subdir", "file3.txt"), []byte("content of file 3 in subdir"), 0644)

	// Test single tar (no split)
	outputPath := filepath.Join(tempDir, "output")
	opts := TarOptions{
		SourceDir:      sourceDir,
		OutputPath:     outputPath,
		SplitSize:      0, // no split
		SplitThreshold: 0,
		Compress:       true,
	}

	result, err := TarDirectory(context.Background(), opts)
	if err != nil {
		t.Fatalf("TarDirectory failed: %v", err)
	}

	if result.FileCount != 3 {
		t.Errorf("expected 3 files, got %d", result.FileCount)
	}
	if result.SplitCount != 1 {
		t.Errorf("expected 1 split, got %d", result.SplitCount)
	}
	if len(result.Files) != 1 {
		t.Errorf("expected 1 output file, got %d", len(result.Files))
	}

	// Verify the tar.gz file exists and is valid
	tarPath := result.Files[0]
	if _, err := os.Stat(tarPath); err != nil {
		t.Fatalf("tar file not found: %v", err)
	}

	// Open and verify contents
	f, err := os.Open(tarPath)
	if err != nil {
		t.Fatalf("failed to open tar file: %v", err)
	}
	defer f.Close()

	gr, err := gzip.NewReader(f)
	if err != nil {
		t.Fatalf("failed to create gzip reader: %v", err)
	}
	defer gr.Close()

	tr := tar.NewReader(gr)
	fileCount := 0
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("failed to read tar entry: %v", err)
		}
		// Only count regular files, not directories
		if hdr.Typeflag == tar.TypeReg {
			fileCount++
		}
	}

	if fileCount != 3 {
		t.Errorf("expected 3 files in tar, got %d", fileCount)
	}

	t.Logf("Single tar test passed: %d files, size=%d bytes", result.FileCount, result.TarSize)
}

func TestTarDirectorySplit(t *testing.T) {
	// Create temp directory with test files
	tempDir := t.TempDir()
	sourceDir := filepath.Join(tempDir, "source")
	os.MkdirAll(sourceDir, 0755)
	
	// Create larger test files to trigger split
	// Each file is 100 bytes
	for i := 0; i < 5; i++ {
		content := make([]byte, 100)
		for j := range content {
			content[j] = byte('A' + i)
		}
		os.WriteFile(filepath.Join(sourceDir, filepath.Base(tempDir)+string(rune('A'+i))+".txt"), content, 0644)
	}

	// Test split tar - split at 150 bytes (should create multiple parts)
	outputPath := filepath.Join(tempDir, "output")
	opts := TarOptions{
		SourceDir:      sourceDir,
		OutputPath:     outputPath,
		SplitSize:      150,  // 150 bytes per part
		SplitThreshold: 100,  // threshold lower than total size
		Compress:       false, // no compression for predictable sizes
	}

	result, err := TarDirectory(context.Background(), opts)
	if err != nil {
		t.Fatalf("TarDirectory failed: %v", err)
	}

	if result.FileCount != 5 {
		t.Errorf("expected 5 files, got %d", result.FileCount)
	}
	if result.SplitCount < 2 {
		t.Errorf("expected at least 2 splits, got %d", result.SplitCount)
	}
	if len(result.Files) < 2 {
		t.Errorf("expected at least 2 output files, got %d", len(result.Files))
	}

	// Verify all part files exist
	for _, partPath := range result.Files {
		if _, err := os.Stat(partPath); err != nil {
			t.Errorf("part file not found: %s", partPath)
		}
	}

	t.Logf("Split tar test passed: %d files, %d parts, total tar size=%d bytes", 
		result.FileCount, result.SplitCount, result.TarSize)
}

func TestTarDirectoryNoSplitBelowThreshold(t *testing.T) {
	// Create temp directory with small test files
	tempDir := t.TempDir()
	sourceDir := filepath.Join(tempDir, "source")
	os.MkdirAll(sourceDir, 0755)
	
	// Create small files (total < 100 bytes)
	os.WriteFile(filepath.Join(sourceDir, "small1.txt"), []byte("small"), 0644)
	os.WriteFile(filepath.Join(sourceDir, "small2.txt"), []byte("tiny"), 0644)

	// Test with split settings but below threshold
	outputPath := filepath.Join(tempDir, "output")
	opts := TarOptions{
		SourceDir:      sourceDir,
		OutputPath:     outputPath,
		SplitSize:      50,   // small split size
		SplitThreshold: 1000, // but threshold is higher than total
		Compress:       true,
	}

	result, err := TarDirectory(context.Background(), opts)
	if err != nil {
		t.Fatalf("TarDirectory failed: %v", err)
	}

	// Should not split because total size is below threshold
	if result.SplitCount != 1 {
		t.Errorf("expected 1 part (no split), got %d", result.SplitCount)
	}

	t.Logf("No-split below threshold test passed: %d files, %d parts", 
		result.FileCount, result.SplitCount)
}

func TestTarDirectoryProgress(t *testing.T) {
	// Create temp directory with test files
	tempDir := t.TempDir()
	sourceDir := filepath.Join(tempDir, "source")
	os.MkdirAll(sourceDir, 0755)
	
	os.WriteFile(filepath.Join(sourceDir, "file1.txt"), []byte("content 1"), 0644)
	os.WriteFile(filepath.Join(sourceDir, "file2.txt"), []byte("content 2"), 0644)

	// Track progress calls
	var progressCalls []string
	outputPath := filepath.Join(tempDir, "output")
	opts := TarOptions{
		SourceDir:  sourceDir,
		OutputPath: outputPath,
		Compress:   true,
		Progress: func(current, total int64, file string) {
			progressCalls = append(progressCalls, file)
		},
	}

	result, err := TarDirectory(context.Background(), opts)
	if err != nil {
		t.Fatalf("TarDirectory failed: %v", err)
	}

	if len(progressCalls) != result.FileCount {
		t.Errorf("expected %d progress calls, got %d", result.FileCount, len(progressCalls))
	}

	t.Logf("Progress test passed: %d progress calls for %d files", 
		len(progressCalls), result.FileCount)
}

func TestTarDirectoryCancel(t *testing.T) {
	// Create temp directory with test files
	tempDir := t.TempDir()
	sourceDir := filepath.Join(tempDir, "source")
	os.MkdirAll(sourceDir, 0755)
	
	os.WriteFile(filepath.Join(sourceDir, "file1.txt"), []byte("content"), 0644)

	// Create already-canceled context
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	outputPath := filepath.Join(tempDir, "output")
	opts := TarOptions{
		SourceDir:  sourceDir,
		OutputPath: outputPath,
		Compress:   true,
	}

	_, err := TarDirectory(ctx, opts)
	if err == nil {
		t.Error("expected error due to canceled context")
	}

	t.Logf("Cancel test passed: got expected error: %v", err)
}
