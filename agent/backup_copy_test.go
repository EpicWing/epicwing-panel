package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBkCopyCopiesAndVerifies(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.tar.gz")
	if err := os.WriteFile(src, []byte("backup-bytes"), 0o600); err != nil {
		t.Fatal(err)
	}

	dest := filepath.Join(dir, "dest.tar.gz")
	size, sum, err := bkCopy(src, dest, "")
	if err != nil {
		t.Fatal(err)
	}
	if size != 12 || len(sum) != 64 {
		t.Fatalf("size=%d sum=%q", size, sum)
	}
	got, err := os.ReadFile(dest)
	if err != nil || string(got) != "backup-bytes" {
		t.Fatalf("copy differs: %q %v", got, err)
	}

	again := filepath.Join(dir, "again.tar.gz")
	if _, _, err := bkCopy(src, again, sum); err != nil {
		t.Fatalf("matching checksum rejected: %v", err)
	}

	bad := filepath.Join(dir, "bad.tar.gz")
	if _, _, err := bkCopy(src, bad, strings.Repeat("0", 64)); err == nil {
		t.Fatal("a wrong checksum must fail")
	}
	for _, f := range []string{bad, bad + ".part"} {
		if _, err := os.Stat(f); err == nil {
			t.Fatalf("%s must not exist after a failed copy", f)
		}
	}

	if _, _, err := bkCopy(filepath.Join(dir, "missing"), filepath.Join(dir, "x"), ""); err == nil {
		t.Fatal("a missing source must fail")
	}
}
