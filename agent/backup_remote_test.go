package main

import (
	"crypto/md5"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestBkUploadSendsPartsAndRetries(t *testing.T) {
	bkRetryDelay = 0
	var mu sync.Mutex
	got := map[string][]byte{}
	failed := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPut {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		defer mu.Unlock()
		part := r.URL.Query().Get("partNumber")
		if part == "2" && !failed {
			failed = true
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		got[part] = body
		w.Header().Set("ETag", fmt.Sprintf("\"%x\"", md5.Sum(body)))
	}))
	defer srv.Close()

	archive := filepath.Join(t.TempDir(), "a.tar.gz")
	data := []byte(strings.Repeat("0123456789", 25)) // 250 bytes, 3 parts of 100
	if err := os.WriteFile(archive, data, 0o600); err != nil {
		t.Fatal(err)
	}
	urls := []string{
		srv.URL + "/b/k?partNumber=1&X-Amz-Signature=secret",
		srv.URL + "/b/k?partNumber=2&X-Amz-Signature=secret",
		srv.URL + "/b/k?partNumber=3&X-Amz-Signature=secret",
	}
	tags, err := bkUpload(archive, 100, urls)
	if err != nil {
		t.Fatal(err)
	}
	if len(tags) != 3 || !failed {
		t.Fatalf("tags=%v failed=%v", tags, failed)
	}
	joined := string(got["1"]) + string(got["2"]) + string(got["3"])
	if joined != string(data) || len(got["3"]) != 50 {
		t.Fatalf("parts do not add up: %d bytes", len(joined))
	}
	if _, err := bkUpload(archive, 100, urls[:2]); err == nil {
		t.Fatal("a wrong number of links must fail")
	}
}

func TestBkUploadErrorHidesTheSignature(t *testing.T) {
	bkRetryDelay = 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		io.WriteString(w, "<Error><Code>AccessDenied</Code></Error>")
	}))
	defer srv.Close()
	archive := filepath.Join(t.TempDir(), "a.tar.gz")
	os.WriteFile(archive, []byte("x"), 0o600)
	_, err := bkUpload(archive, 100, []string{srv.URL + "/k?X-Amz-Signature=topsecret"})
	if err == nil || !strings.Contains(err.Error(), "AccessDenied") {
		t.Fatalf("err=%v", err)
	}
	srv.Close()
	_, err = bkUpload(archive, 100, []string{srv.URL + "/k?X-Amz-Signature=topsecret"})
	if err == nil || strings.Contains(err.Error(), "topsecret") {
		t.Fatalf("the signature must not show in errors: %v", err)
	}
}

func TestBkFetchChecksTheChecksum(t *testing.T) {
	data := []byte("backup-bytes")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write(data)
	}))
	defer srv.Close()
	sum := sha256.Sum256(data)
	want := hex.EncodeToString(sum[:])
	dir := t.TempDir()

	dest := filepath.Join(dir, "ok.tar.gz")
	size, got, err := bkFetch(srv.URL+"/k", dest, want)
	if err != nil || size != int64(len(data)) || got != want {
		t.Fatalf("size=%d sum=%s err=%v", size, got, err)
	}
	if b, _ := os.ReadFile(dest); string(b) != string(data) {
		t.Fatal("content differs")
	}

	bad := filepath.Join(dir, "bad.tar.gz")
	if _, _, err := bkFetch(srv.URL+"/k", bad, strings.Repeat("0", 64)); err == nil {
		t.Fatal("a wrong checksum must fail")
	}
	for _, f := range []string{bad, bad + ".part"} {
		if _, err := os.Stat(f); err == nil {
			t.Fatalf("%s must not exist", f)
		}
	}
}

func TestBkValidURL(t *testing.T) {
	for _, ok := range []string{"https://s3.example.com/b/k?x=1", "http://127.0.0.1:9000/b/k"} {
		if bkValidURL(ok) != nil {
			t.Fatalf("%s should be valid", ok)
		}
	}
	for _, bad := range []string{"", "file:///etc/passwd", "ftp://x/y", "https://"} {
		if bkValidURL(bad) == nil {
			t.Fatalf("%q should be invalid", bad)
		}
	}
}
