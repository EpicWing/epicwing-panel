package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type uaEntry struct {
	name string
	body string
	mode int64
	typ  byte
	link string
}

func uaZip(t *testing.T, entries []uaEntry) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, e := range entries {
		h := &zip.FileHeader{Name: e.name, Method: zip.Deflate}
		if e.mode != 0 {
			h.SetMode(os.FileMode(e.mode))
		}
		w, err := zw.CreateHeader(h)
		if err != nil {
			t.Fatal(err)
		}
		if e.body != "" {
			if _, err := w.Write([]byte(e.body)); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func uaTarGz(t *testing.T, entries []uaEntry) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	for _, e := range entries {
		typ := e.typ
		if typ == 0 {
			typ = tar.TypeReg
		}
		mode := e.mode
		if mode == 0 {
			mode = 0o644
		}
		h := &tar.Header{Name: e.name, Typeflag: typ, Mode: mode, Linkname: e.link}
		if typ == tar.TypeReg {
			h.Size = int64(len(e.body))
		}
		if err := tw.WriteHeader(h); err != nil {
			t.Fatal(err)
		}
		if h.Size > 0 {
			if _, err := tw.Write([]byte(e.body)); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func uaSetup(t *testing.T) (*os.Root, string, string) {
	t.Helper()
	base := t.TempDir()
	server := filepath.Join(base, "server")
	if err := os.Mkdir(server, 0o755); err != nil {
		t.Fatal(err)
	}
	root, err := os.OpenRoot(server)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { root.Close() })
	return root, server, base
}

func uaPut(t *testing.T, server, name string, data []byte) {
	t.Helper()
	full := filepath.Join(server, name)
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func uaLimits(t *testing.T, entries int, size int64) {
	t.Helper()
	oldEntries, oldBytes := unarchiveMaxEntries, unarchiveMaxBytes
	unarchiveMaxEntries, unarchiveMaxBytes = entries, size
	t.Cleanup(func() { unarchiveMaxEntries, unarchiveMaxBytes = oldEntries, oldBytes })
}

func uaFail(t *testing.T, err error, needle string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected an error containing %q, got none", needle)
	}
	if !strings.Contains(err.Error(), needle) {
		t.Fatalf("expected an error containing %q, got %q", needle, err.Error())
	}
}

func uaMissing(t *testing.T, name string) {
	t.Helper()
	if _, err := os.Lstat(name); err == nil {
		t.Fatalf("%s must not exist", name)
	}
}

func uaRead(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestUnarchiveZip(t *testing.T) {
	root, server, _ := uaSetup(t)
	uaPut(t, server, "pack.zip", uaZip(t, []uaEntry{
		{name: "plugins/"},
		{name: "plugins/a.txt", body: "hello"},
		{name: "run.sh", body: "#!/bin/sh\n", mode: 0o755},
		{name: "readme.md", body: "hi"},
	}))
	res, err := fileDecompress(root, "pack.zip", "out")
	if err != nil {
		t.Fatal(err)
	}
	if res["files"] != 3 || res["dirs"] != 1 {
		t.Fatalf("unexpected result %v", res)
	}
	if uaRead(t, filepath.Join(server, "out", "plugins", "a.txt")) != "hello" {
		t.Fatal("wrong content")
	}
	run, _ := os.Stat(filepath.Join(server, "out", "run.sh"))
	if run.Mode()&0o111 == 0 {
		t.Fatal("run.sh lost its executable bit")
	}
	readme, _ := os.Stat(filepath.Join(server, "out", "readme.md"))
	if readme.Mode()&0o111 != 0 {
		t.Fatal("readme.md must not be executable")
	}
}

func TestUnarchiveTarGz(t *testing.T) {
	root, server, _ := uaSetup(t)
	uaPut(t, server, "pack.tar.gz", uaTarGz(t, []uaEntry{
		{name: "./", typ: tar.TypeDir, mode: 0o755},
		{name: "bot/", typ: tar.TypeDir, mode: 0o755},
		{name: "bot/config.yml", body: "a: 1"},
		{name: "bot/start.sh", body: "x", mode: 0o755},
	}))
	res, err := fileDecompress(root, "pack.tar.gz", "")
	if err != nil {
		t.Fatal(err)
	}
	if res["files"] != 2 || res["dirs"] != 1 {
		t.Fatalf("unexpected result %v", res)
	}
	if uaRead(t, filepath.Join(server, "bot", "config.yml")) != "a: 1" {
		t.Fatal("wrong content")
	}
	start, _ := os.Stat(filepath.Join(server, "bot", "start.sh"))
	if start.Mode()&0o111 == 0 {
		t.Fatal("start.sh lost its executable bit")
	}
}

func TestUnarchiveTgzExtension(t *testing.T) {
	root, server, _ := uaSetup(t)
	uaPut(t, server, "a.tgz", uaTarGz(t, []uaEntry{{name: "f.txt", body: "x"}}))
	if _, err := fileDecompress(root, "a.tgz", ""); err != nil {
		t.Fatal(err)
	}
	if uaRead(t, filepath.Join(server, "f.txt")) != "x" {
		t.Fatal("wrong content")
	}
}

func TestUnarchiveDefaultsToArchiveFolder(t *testing.T) {
	root, server, _ := uaSetup(t)
	uaPut(t, server, "sub/x.zip", uaZip(t, []uaEntry{{name: "f.txt", body: "x"}}))
	if _, err := fileDecompress(root, "sub/x.zip", ""); err != nil {
		t.Fatal(err)
	}
	if uaRead(t, filepath.Join(server, "sub", "f.txt")) != "x" {
		t.Fatal("not extracted next to the archive")
	}
}

func TestUnarchiveOverwritesFiles(t *testing.T) {
	root, server, _ := uaSetup(t)
	uaPut(t, server, "a.txt", []byte("old"))
	uaPut(t, server, "p.zip", uaZip(t, []uaEntry{{name: "a.txt", body: "new"}}))
	if _, err := fileDecompress(root, "p.zip", ""); err != nil {
		t.Fatal(err)
	}
	if uaRead(t, filepath.Join(server, "a.txt")) != "new" {
		t.Fatal("file was not overwritten")
	}
}

func TestUnarchiveRejectsTraversal(t *testing.T) {
	for _, name := range []string{"../evil.txt", "a/../../evil.txt", "/abs.txt", `..\evil.txt`} {
		root, server, base := uaSetup(t)
		uaPut(t, server, "p.zip", uaZip(t, []uaEntry{{name: name, body: "x"}}))
		_, err := fileDecompress(root, "p.zip", "")
		uaFail(t, err, "unsafe path in archive")
		uaMissing(t, filepath.Join(base, "evil.txt"))
		uaMissing(t, "/abs.txt")
	}
	root, server, base := uaSetup(t)
	uaPut(t, server, "p.tar.gz", uaTarGz(t, []uaEntry{{name: "../evil.txt", body: "x"}}))
	_, err := fileDecompress(root, "p.tar.gz", "")
	uaFail(t, err, "unsafe path in archive")
	uaMissing(t, filepath.Join(base, "evil.txt"))
}

func TestUnarchiveStopsAtSymlinkLeadingOutside(t *testing.T) {
	root, server, base := uaSetup(t)
	outside := filepath.Join(base, "outside")
	if err := os.Mkdir(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(server, "link")); err != nil {
		t.Fatal(err)
	}
	uaPut(t, server, "p.zip", uaZip(t, []uaEntry{{name: "link/pwn.txt", body: "x"}}))
	_, err := fileDecompress(root, "p.zip", "")
	uaFail(t, err, "escapes")
	uaMissing(t, filepath.Join(outside, "pwn.txt"))
}

func TestUnarchiveSkipsSymlinkEntries(t *testing.T) {
	root, server, base := uaSetup(t)
	uaPut(t, server, "p.tar.gz", uaTarGz(t, []uaEntry{
		{name: "link", typ: tar.TypeSymlink, link: "../outside"},
		{name: "link/pwn.txt", body: "x"},
	}))
	res, err := fileDecompress(root, "p.tar.gz", "")
	if err != nil {
		t.Fatal(err)
	}
	if res["skipped"] != 1 {
		t.Fatalf("symlink entry not skipped: %v", res)
	}
	info, err := os.Lstat(filepath.Join(server, "link"))
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		t.Fatal("link must be a plain directory, not a symlink")
	}
	uaMissing(t, filepath.Join(base, "outside"))
}

func TestUnarchiveEntryLimit(t *testing.T) {
	uaLimits(t, 3, 1<<20)
	root, server, _ := uaSetup(t)
	uaPut(t, server, "p.zip", uaZip(t, []uaEntry{
		{name: "1", body: "x"}, {name: "2", body: "x"}, {name: "3", body: "x"}, {name: "4", body: "x"},
	}))
	_, err := fileDecompress(root, "p.zip", "")
	uaFail(t, err, "archive limit exceeded")
	uaPut(t, server, "p.tar.gz", uaTarGz(t, []uaEntry{
		{name: "1", body: "x"}, {name: "2", body: "x"}, {name: "3", body: "x"}, {name: "4", body: "x"},
	}))
	_, err = fileDecompress(root, "p.tar.gz", "")
	uaFail(t, err, "archive limit exceeded")
}

func TestUnarchiveSizeLimit(t *testing.T) {
	uaLimits(t, 100, 10)
	root, server, _ := uaSetup(t)
	uaPut(t, server, "p.zip", uaZip(t, []uaEntry{{name: "big.txt", body: strings.Repeat("x", 100)}}))
	_, err := fileDecompress(root, "p.zip", "")
	uaFail(t, err, "archive limit exceeded")
	uaMissing(t, filepath.Join(server, "big.txt"))
	uaPut(t, server, "p.tar.gz", uaTarGz(t, []uaEntry{
		{name: "a", body: "123456"}, {name: "b", body: "123456"},
	}))
	_, err = fileDecompress(root, "p.tar.gz", "")
	uaFail(t, err, "archive limit exceeded")
}

func TestUnarchiveRejectsBadInput(t *testing.T) {
	root, server, _ := uaSetup(t)
	uaPut(t, server, "a.rar", []byte("x"))
	_, err := fileDecompress(root, "a.rar", "")
	uaFail(t, err, "unsupported archive")
	uaPut(t, server, "bad.zip", []byte("not a zip"))
	_, err = fileDecompress(root, "bad.zip", "")
	uaFail(t, err, "invalid archive")
	uaPut(t, server, "bad.tar.gz", []byte("not gzip"))
	_, err = fileDecompress(root, "bad.tar.gz", "")
	uaFail(t, err, "invalid archive")
	_, err = fileDecompress(root, "nope.zip", "")
	uaFail(t, err, "no such file")
	if err := os.Mkdir(filepath.Join(server, "d.zip"), 0o755); err != nil {
		t.Fatal(err)
	}
	_, err = fileDecompress(root, "d.zip", "")
	uaFail(t, err, "not a regular file")
}
