package main

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func testRoot(t *testing.T) (*os.Root, string) {
	t.Helper()
	dir := t.TempDir()
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { root.Close() })
	return root, dir
}

func b64(s string) string { return base64.StdEncoding.EncodeToString([]byte(s)) }

func TestWriteReadRoundtrip(t *testing.T) {
	root, _ := testRoot(t)
	if err := root.Mkdir("a", 0o755); err != nil {
		t.Fatal(err)
	}
	if err := fileWrite(root, "a/b.txt", 0, b64("hello "), true, true); err != nil {
		t.Fatal(err)
	}
	if err := fileWrite(root, "a/b.txt", 6, b64("world"), false, false); err != nil {
		t.Fatal(err)
	}
	res, err := fileRead(root, "/a/b.txt", 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	got, _ := base64.StdEncoding.DecodeString(res["data"].(string))
	if string(got) != "hello world" || res["eof"] != true {
		t.Fatalf("unexpected read: %q %v", got, res["eof"])
	}
}

func TestDotDotStaysInsideRoot(t *testing.T) {
	root, dir := testRoot(t)
	if err := fileWrite(root, "../../forge-escape-test.txt", 0, b64("x"), true, true); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "forge-escape-test.txt")); err != nil {
		t.Fatalf("file should land inside the root: %v", err)
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(dir), "forge-escape-test.txt")); err == nil {
		t.Fatal("file escaped the root")
	}
}

func TestSymlinkEscapeIsRejected(t *testing.T) {
	root, dir := testRoot(t)
	outside := t.TempDir()
	secret := filepath.Join(outside, "secret.txt")
	if err := os.WriteFile(secret, []byte("geheim"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(dir, "dirlink")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(secret, filepath.Join(dir, "filelink")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../../../../etc/passwd", filepath.Join(dir, "rellink")); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"dirlink/secret.txt", "filelink", "rellink"} {
		if _, err := fileRead(root, p, 0, 0); err == nil {
			t.Fatalf("read through %s must fail", p)
		}
	}
	if err := fileWrite(root, "dirlink/new.txt", 0, b64("x"), true, true); err == nil {
		t.Fatal("write through symlink must fail")
	}
	if _, err := os.Stat(filepath.Join(outside, "new.txt")); err == nil {
		t.Fatal("file was created outside the root")
	}
	if _, err := fileList(root, "dirlink", 0); err == nil {
		t.Fatal("list through symlink must fail")
	}
}

func TestListOrderAndPaging(t *testing.T) {
	root, _ := testRoot(t)
	root.Mkdir("zdir", 0o755)
	for _, n := range []string{"b", "a", "c"} {
		if err := fileWrite(root, n, 0, "", true, true); err != nil {
			t.Fatal(err)
		}
	}
	res, err := fileList(root, "", 0)
	if err != nil {
		t.Fatal(err)
	}
	entries := res["entries"].([]map[string]any)
	if len(entries) != 4 || entries[0]["name"] != "zdir" || entries[1]["name"] != "a" || res["total"] != 4 || res["next"] != -1 {
		t.Fatalf("unexpected listing: %v", res)
	}
}

func TestRename(t *testing.T) {
	root, _ := testRoot(t)
	root.Mkdir("d", 0o755)
	fileWrite(root, "one", 0, b64("1"), true, true)
	fileWrite(root, "two", 0, b64("2"), true, true)
	if err := fileRename(root, "one", "d/uno"); err != nil {
		t.Fatal(err)
	}
	if _, err := root.Lstat("d/uno"); err != nil {
		t.Fatal("renamed file missing")
	}
	if err := fileRename(root, "d/uno", "two"); err == nil {
		t.Fatal("rename onto an existing target must fail")
	}
	if err := fileRename(root, "d/uno", "."); err == nil {
		t.Fatal("rename onto the root must fail")
	}
}

func TestDelete(t *testing.T) {
	root, dir := testRoot(t)
	outside := t.TempDir()
	keep := filepath.Join(outside, "keep.txt")
	os.WriteFile(keep, []byte("x"), 0o644)
	root.Mkdir("tree", 0o755)
	root.Mkdir("tree/sub", 0o755)
	fileWrite(root, "tree/sub/f", 0, b64("x"), true, true)
	os.Symlink(outside, filepath.Join(dir, "tree", "link"))
	if err := fileDelete(root, "tree", false); err == nil {
		t.Fatal("non-recursive delete of a filled directory must fail")
	}
	if err := fileDelete(root, "tree", true); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(keep); err != nil {
		t.Fatal("recursive delete followed a symlink out of the root")
	}
	if err := fileDelete(root, "/", true); err == nil {
		t.Fatal("deleting the root must fail")
	}
}

func TestFifoIsRejected(t *testing.T) {
	root, dir := testRoot(t)
	if err := syscall.Mkfifo(filepath.Join(dir, "pipe"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := fileRead(root, "pipe", 0, 0); err == nil {
		t.Fatal("reading a FIFO must fail")
	}
}
