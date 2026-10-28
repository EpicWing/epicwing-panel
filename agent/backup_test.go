package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func bkPut(t *testing.T, base, rel, content string) {
	t.Helper()
	p := filepath.Join(base, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func bkGet(base, rel string) (string, bool) {
	b, err := os.ReadFile(filepath.Join(base, filepath.FromSlash(rel)))
	return string(b), err == nil
}

func TestBkRoundTrip(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "src")
	big := strings.Repeat("abc", 50000)
	bkPut(t, src, "server.properties", "motd=hi")
	bkPut(t, src, "world/data/level.dat", big)
	bkPut(t, src, "logs/latest.log", "log")
	bkPut(t, src, "cache/x.tmp", "tmp")
	if err := os.Symlink("/etc/passwd", filepath.Join(src, "link")); err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(tmp, "b", "x.tar.gz")
	if err := os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
		t.Fatal(err)
	}
	size, sum, err := bkCreate(src, dest, "logs/\n*.tmp\n")
	if err != nil || size == 0 || len(sum) != 64 {
		t.Fatalf("create: size=%d sum=%q err=%v", size, sum, err)
	}
	if got, _ := bkSum(dest); got != sum {
		t.Fatalf("checksum differs: %s vs %s", got, sum)
	}

	bkPut(t, src, "new.txt", "new")
	if err := os.Remove(filepath.Join(src, "server.properties")); err != nil {
		t.Fatal(err)
	}
	if err := bkRestore(dest, src); err != nil {
		t.Fatalf("restore: %v", err)
	}
	if v, ok := bkGet(src, "server.properties"); !ok || v != "motd=hi" {
		t.Fatalf("server.properties not restored: %q %v", v, ok)
	}
	if v, ok := bkGet(src, "world/data/level.dat"); !ok || v != big {
		t.Fatal("level.dat not restored")
	}
	for _, gone := range []string{"new.txt", "logs/latest.log", "cache/x.tmp", "link"} {
		if _, err := os.Lstat(filepath.Join(src, gone)); err == nil {
			t.Fatalf("%s should not exist after the restore", gone)
		}
	}
	for _, left := range []string{src + ".restore-new", src + ".restore-old"} {
		if _, err := os.Lstat(left); err == nil {
			t.Fatalf("%s was not cleaned up", left)
		}
	}
}

func TestBkRestoreRejectsTraversal(t *testing.T) {
	tmp := t.TempDir()
	base := filepath.Join(tmp, "srv")
	bkPut(t, base, "keep.txt", "keep")
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	if err := tw.WriteHeader(&tar.Header{Name: "../evil.txt", Mode: 0o644, Size: 4, Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	tw.Write([]byte("evil"))
	tw.Close()
	gz.Close()
	archive := filepath.Join(tmp, "evil.tar.gz")
	if err := os.WriteFile(archive, buf.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := bkRestore(archive, base); err == nil {
		t.Fatal("restore of an unsafe archive must fail")
	}
	if _, err := os.Stat(filepath.Join(tmp, "evil.txt")); err == nil {
		t.Fatal("file was written outside the server directory")
	}
	if v, ok := bkGet(base, "keep.txt"); !ok || v != "keep" {
		t.Fatal("the server directory changed although the restore failed")
	}
	if _, err := os.Lstat(base + ".restore-new"); err == nil {
		t.Fatal("staging directory was not removed")
	}
}

func TestBkIgnoreRules(t *testing.T) {
	cases := []struct {
		rules string
		rel   string
		dir   bool
		want  bool
	}{
		{"logs/", "logs", true, true},
		{"logs/", "logs", false, false},
		{"*.tmp", "a/b/c.tmp", false, true},
		{"/cache", "cache", true, true},
		{"/cache", "x/cache", true, false},
		{"world/*.log", "world/a.log", false, true},
		{"*.log\n!keep.log", "keep.log", false, false},
		{"*.log\n!keep.log", "a.log", false, true},
		{"# comment\n\n", "a", false, false},
	}
	for _, c := range cases {
		if got := bkIgnored(parseBkRules(c.rules), c.rel, c.dir); got != c.want {
			t.Errorf("rules %q path %q dir=%v: got %v want %v", c.rules, c.rel, c.dir, got, c.want)
		}
	}
}
