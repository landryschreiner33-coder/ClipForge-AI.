package main

import (
	"bufio"
	_ "embed"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
)

//go:embed bootstrap.ps1
var bootstrap []byte

//go:embed app.zip
var appArchive []byte

func prepareBundle(parent string) (string, string, string, error) {
	dir, err := os.MkdirTemp(parent, "ClipFoundry-Open-")
	if err != nil {
		return "", "", "", fmt.Errorf("create setup folder: %w", err)
	}
	script := filepath.Join(dir, "setup.ps1")
	if err := os.WriteFile(script, bootstrap, 0600); err != nil {
		os.RemoveAll(dir)
		return "", "", "", fmt.Errorf("prepare setup: %w", err)
	}
	archive := filepath.Join(dir, "app.zip")
	if err := os.WriteFile(archive, appArchive, 0600); err != nil {
		os.RemoveAll(dir)
		return "", "", "", fmt.Errorf("prepare included app files: %w", err)
	}
	return dir, script, archive, nil
}

func run() error {
	if runtime.GOOS != "windows" {
		return fmt.Errorf("this launcher runs on Windows 10 or Windows 11")
	}
	dir, script, archive, err := prepareBundle("")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)
	// Pass the path as data. The command text is fixed even if a username contains shell characters.
	loader := "$raw = [IO.File]::ReadAllText($env:CF_OPEN_SCRIPT); & ([scriptblock]::Create($raw))"
	cmd := exec.Command("powershell.exe", "-NoLogo", "-NoProfile", "-Command", loader)
	cmd.Env = append(os.Environ(), "CF_OPEN_SCRIPT="+script, "CF_OPEN_ARCHIVE="+archive)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("setup did not finish: %w", err)
	}
	return nil
}

func main() {
	fmt.Println("ClipFoundry - bundled setup (app files included)")
	if err := run(); err != nil {
		fmt.Println(err)
		fmt.Println("Press Enter to close this window. You can reopen the launcher to retry.")
		_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
		os.Exit(1)
	}
}
