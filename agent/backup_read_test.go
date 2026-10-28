package main

import (
	"bytes"
	"encoding/base64"
	"os"
	"path/filepath"
	"testing"
)

func TestBkReadChunkRoundTrip(t *testing.T) {
	file := filepath.Join(t.TempDir(), "a.tar.gz")
	want := make([]byte, 20000)
	for i := range want {
		want[i] = byte(i * 7)
	}
	if err := os.WriteFile(file, want, 0o600); err != nil {
		t.Fatal(err)
	}
	var got []byte
	var size int64
	offset := int64(0)
	for {
		res, err := bkReadChunk(file, offset, bkReadMax)
		if err != nil {
			t.Fatal(err)
		}
		size = res["size"].(int64)
		chunk, err := base64.StdEncoding.DecodeString(res["data"].(string))
		if err != nil {
			t.Fatal(err)
		}
		got = append(got, chunk...)
		offset += int64(len(chunk))
		if len(chunk) == 0 || offset >= size {
			break
		}
	}
	if size != int64(len(want)) || !bytes.Equal(got, want) {
		t.Fatalf("round trip mismatch: size %d, got %d bytes", size, len(got))
	}
}

func TestBkReadChunkRejects(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "a.tar.gz")
	if err := os.WriteFile(file, []byte("abc"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link.tar.gz")
	if err := os.Symlink(file, link); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		path   string
		offset int64
		length int
	}{
		{filepath.Join(dir, "missing.tar.gz"), 0, 10},
		{link, 0, 10},
		{file, -1, 10},
		{file, 0, 0},
		{file, 0, bkReadMax + 1},
		{file, 4, 10},
	}
	for _, c := range cases {
		if _, err := bkReadChunk(c.path, c.offset, c.length); err == nil {
			t.Errorf("expected an error for %+v", c)
		}
	}
}
