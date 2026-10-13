package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"testing"
)

func TestPrepareBundleWritesVerifiedArchiveAndScript(t *testing.T) {
	parent := filepath.Join(t.TempDir(), "space & percent% bang! Unicode-é")
	if err := os.Mkdir(parent, 0700); err != nil {
		t.Fatal(err)
	}
	dir, script, archive, err := prepareBundle(parent)
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)
	actual, err := os.ReadFile(archive)
	if err != nil {
		t.Fatal(err)
	}
	archiveHash := embeddedValue(t, "ArchiveHash", 64)
	if got := fmt.Sprintf("%x", sha256.Sum256(actual)); got != archiveHash {
		t.Fatalf("included app bytes differ: %s", got)
	}
	actualScript, err := os.ReadFile(script)
	if err != nil || !bytes.Equal(actualScript, bootstrap) {
		t.Fatalf("script was not prepared intact: %v", err)
	}
	items, err := os.ReadDir(dir)
	if err != nil || len(items) != 2 {
		t.Fatalf("unexpected temporary files: %v, %v", items, err)
	}
}

func TestPrepareBundleReportsFailureWithoutTouchingExistingFiles(t *testing.T) {
	parent := t.TempDir()
	occupied := filepath.Join(parent, "existing-owner-file")
	if err := os.WriteFile(occupied, []byte("preserve owner data"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := prepareBundle(occupied); err == nil {
		t.Fatal("creating a temporary directory inside a file must fail")
	}
	actual, err := os.ReadFile(occupied)
	if err != nil || string(actual) != "preserve owner data" {
		t.Fatalf("existing file changed: %v", err)
	}
}

func embeddedValue(t *testing.T, name string, length int) string {
	t.Helper()
	pattern := regexp.MustCompile(`(?m)^\$` + regexp.QuoteMeta(name) + ` = '([0-9a-f]{` +
		fmt.Sprint(length) + `})'\r?$`)
	match := pattern.FindSubmatch(bootstrap)
	if len(match) != 2 {
		t.Fatalf("embedded setup has no exact %s", name)
	}
	return string(match[1])
}

func TestEmbeddedArchiveMatchesPinnedRevisionAndLauncher(t *testing.T) {
	revision := embeddedValue(t, "Commit", 40)
	startHash := embeddedValue(t, "StartHash", 64)
	archive, err := zip.NewReader(bytes.NewReader(appArchive), int64(len(appArchive)))
	if err != nil {
		t.Fatal(err)
	}
	prefix := "ClipForge-AI.-" + revision + "/"
	startFound, frontendFound := false, false
	for _, file := range archive.File {
		if !bytes.HasPrefix([]byte(file.Name), []byte(prefix)) {
			t.Fatalf("unexpected archive revision folder: %s", file.Name)
		}
		if file.Name == prefix+"frontend/dist/index.html" {
			frontendFound = true
		}
		if file.Name != prefix+"start.bat" {
			continue
		}
		input, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		hash := sha256.New()
		_, err = io.Copy(hash, input)
		input.Close()
		if err != nil {
			t.Fatal(err)
		}
		if got := fmt.Sprintf("%x", hash.Sum(nil)); got != startHash {
			t.Fatalf("pinned start.bat differs: %s", got)
		}
		startFound = true
	}
	if !startFound || !frontendFound {
		t.Fatal("embedded archive must include checked launcher and built frontend")
	}
}
