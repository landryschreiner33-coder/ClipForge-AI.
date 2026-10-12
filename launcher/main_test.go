package main

import (
	"bytes"
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
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
	const archiveHash = "90a197126d586d0b5ebcbb46fc08a4cd18a5f38f00f555612e6a73853ae7881a"
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
