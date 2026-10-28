package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const transferTestOrigin = "https://panel.example"

func transferTestSetup(t *testing.T) (*httptest.Server, *transferTicketStore, string) {
	t.Helper()
	data := t.TempDir()
	dir := filepath.Join(data, "web-1")
	if err := os.Mkdir(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	store := newTransferTicketStore()
	srv := httptest.NewServer(newTransferServer(store, func(name string) string { return filepath.Join(data, name) }))
	t.Cleanup(srv.Close)
	return srv, store, dir
}

func transferIssue(t *testing.T, store *transferTicketStore, dir, p string) string {
	t.Helper()
	rel, err := cleanPath(p)
	if err != nil {
		t.Fatal(err)
	}
	token, err := store.issue(transferTicket{name: "web-1", rel: rel, dir: dir, origin: transferTestOrigin})
	if err != nil {
		t.Fatal(err)
	}
	return token
}

func transferDo(t *testing.T, method, target, origin, byteRange string, body io.Reader) (*http.Response, []byte) {
	t.Helper()
	req, err := http.NewRequest(method, target, body)
	if err != nil {
		t.Fatal(err)
	}
	if origin != "" {
		req.Header.Set("Origin", origin)
	}
	if byteRange != "" {
		req.Header.Set("Range", byteRange)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return resp, data
}

func transferURL(srv *httptest.Server, token string) string {
	return srv.URL + transferURLPrefix + token
}

func transferWaitUntil(t *testing.T, what string, check func() bool) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if check() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timeout: %s", what)
}

func TestTransferUploadWritesFile(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	token := transferIssue(t, store, transferUpload, "hello.txt")
	resp, _ := transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("hello world"))
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("status %d", resp.StatusCode)
	}
	got, err := os.ReadFile(filepath.Join(dir, "hello.txt"))
	if err != nil || string(got) != "hello world" {
		t.Fatalf("file content %q, err %v", got, err)
	}
	if parts, _ := filepath.Glob(filepath.Join(dir, "*.part")); len(parts) != 0 {
		t.Fatalf("part file left behind: %v", parts)
	}
	resp, _ = transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("again"))
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("a used ticket must be refused, got %d", resp.StatusCode)
	}
}

func TestTransferUploadOverwrites(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	token := transferIssue(t, store, transferUpload, "a.txt")
	resp, _ := transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("new content"))
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("status %d", resp.StatusCode)
	}
	got, _ := os.ReadFile(filepath.Join(dir, "a.txt"))
	if string(got) != "new content" {
		t.Fatalf("file content %q", got)
	}
	if parts, _ := filepath.Glob(filepath.Join(dir, "*.part")); len(parts) != 0 {
		t.Fatalf("part file left behind: %v", parts)
	}
}

func TestTransferUploadChecksOrigin(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	token := transferIssue(t, store, transferUpload, "o.txt")
	for _, origin := range []string{"", "https://evil.example"} {
		resp, _ := transferDo(t, http.MethodPut, transferURL(srv, token), origin, "", strings.NewReader("x"))
		if resp.StatusCode != http.StatusForbidden {
			t.Fatalf("origin %q: status %d", origin, resp.StatusCode)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "o.txt")); err == nil {
		t.Fatal("nothing may be written for a refused request")
	}
	resp, _ := transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("x"))
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("refused requests must not burn the ticket, got %d", resp.StatusCode)
	}
}

func TestTransferUploadStaysInRoot(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	token := transferIssue(t, store, transferUpload, "../escape.txt")
	resp, _ := transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("x"))
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("status %d", resp.StatusCode)
	}
	if _, err := os.Stat(filepath.Join(dir, "escape.txt")); err != nil {
		t.Fatalf("file must land inside the server folder: %v", err)
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(dir), "escape.txt")); err == nil {
		t.Fatal("file escaped the server folder")
	}
}

func TestTransferTicketDirection(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	if err := os.WriteFile(filepath.Join(dir, "d.txt"), []byte("data"), 0o644); err != nil {
		t.Fatal(err)
	}
	token := transferIssue(t, store, transferDownload, "d.txt")
	resp, _ := transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("x"))
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("a download ticket must not allow an upload, got %d", resp.StatusCode)
	}
	resp, body := transferDo(t, http.MethodGet, transferURL(srv, token), "", "", nil)
	if resp.StatusCode != http.StatusOK || string(body) != "data" {
		t.Fatalf("download failed after a refused request: %d %q", resp.StatusCode, body)
	}
}

func TestTransferDownloadRange(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	if err := os.WriteFile(filepath.Join(dir, "data.bin"), []byte("0123456789"), 0o644); err != nil {
		t.Fatal(err)
	}
	token := transferIssue(t, store, transferDownload, "data.bin")
	resp, body := transferDo(t, http.MethodGet, transferURL(srv, token), "", "bytes=2-5", nil)
	if resp.StatusCode != http.StatusPartialContent || string(body) != "2345" {
		t.Fatalf("range answer: %d %q", resp.StatusCode, body)
	}
	if !strings.Contains(resp.Header.Get("Content-Disposition"), "data.bin") {
		t.Fatalf("Content-Disposition: %q", resp.Header.Get("Content-Disposition"))
	}
	resp, _ = transferDo(t, http.MethodGet, transferURL(srv, token), "", "", nil)
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("a used ticket must be refused, got %d", resp.StatusCode)
	}
}

func TestTransferTicketExpires(t *testing.T) {
	srv, store, _ := transferTestSetup(t)
	var skew atomic.Int64
	store.now = func() time.Time { return time.Now().Add(time.Duration(skew.Load())) }
	token := transferIssue(t, store, transferDownload, "x.txt")
	skew.Store(int64(2 * time.Minute))
	resp, _ := transferDo(t, http.MethodGet, transferURL(srv, token), "", "", nil)
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("an expired ticket must be refused, got %d", resp.StatusCode)
	}
}

func TestTransferPreflight(t *testing.T) {
	srv, store, _ := transferTestSetup(t)
	token := transferIssue(t, store, transferUpload, "p.txt")
	preflight := func(origin string) *http.Response {
		req, err := http.NewRequest(http.MethodOptions, transferURL(srv, token), nil)
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Origin", origin)
		req.Header.Set("Access-Control-Request-Method", "PUT")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		return resp
	}
	if resp := preflight("https://evil.example"); resp.StatusCode != http.StatusForbidden {
		t.Fatalf("foreign origin: status %d", resp.StatusCode)
	}
	resp := preflight(transferTestOrigin)
	if resp.StatusCode != http.StatusNoContent || resp.Header.Get("Access-Control-Allow-Origin") != transferTestOrigin {
		t.Fatalf("preflight: %d %v", resp.StatusCode, resp.Header)
	}
	put, _ := transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("x"))
	if put.StatusCode != http.StatusNoContent {
		t.Fatalf("the preflight must not burn the ticket, got %d", put.StatusCode)
	}
}

func TestTransferAbortedUploadLeavesNothing(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	token := transferIssue(t, store, transferUpload, "big.bin")
	pr, pw := io.Pipe()
	req, err := http.NewRequest(http.MethodPut, transferURL(srv, token), pr)
	if err != nil {
		t.Fatal(err)
	}
	req.ContentLength = 1000
	req.Header.Set("Origin", transferTestOrigin)
	go func() {
		_, _ = pw.Write([]byte("partial data"))
		deadline := time.Now().Add(2 * time.Second)
		for time.Now().Before(deadline) {
			if _, err := os.Stat(filepath.Join(dir, "big.bin.part")); err == nil {
				break
			}
			time.Sleep(10 * time.Millisecond)
		}
		_ = pw.CloseWithError(errors.New("connection lost"))
	}()
	if resp, err := http.DefaultClient.Do(req); err == nil {
		resp.Body.Close()
		t.Fatal("expected the request to fail")
	}
	transferWaitUntil(t, "part file removed", func() bool {
		entries, _ := os.ReadDir(dir)
		return len(entries) == 0
	})
}

func writeTransferTestCert(t *testing.T, certFile, keyFile, name string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()),
		Subject:      pkix.Name{CommonName: name},
		DNSNames:     []string{name},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	if err := os.WriteFile(certFile, certPEM, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(keyFile, keyPEM, 0o600); err != nil {
		t.Fatal(err)
	}
}

func transferCertName(t *testing.T, der []byte) string {
	t.Helper()
	leaf, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return leaf.Subject.CommonName
}

func transferTouch(t *testing.T, ts time.Time, files ...string) {
	t.Helper()
	for _, f := range files {
		if err := os.Chtimes(f, ts, ts); err != nil {
			t.Fatal(err)
		}
	}
}

func TestTransferCertReloads(t *testing.T) {
	dir := t.TempDir()
	certFile, keyFile := filepath.Join(dir, "cert.pem"), filepath.Join(dir, "key.pem")
	writeTransferTestCert(t, certFile, keyFile, "one.example")
	c := &transferCertReloader{certFile: certFile, keyFile: keyFile}
	cert, err := c.get(nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := transferCertName(t, cert.Certificate[0]); got != "one.example" {
		t.Fatalf("first certificate: %s", got)
	}
	later := time.Now().Add(time.Minute)
	writeTransferTestCert(t, certFile, keyFile, "two.example")
	transferTouch(t, later, certFile, keyFile)
	cert, err = c.get(nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := transferCertName(t, cert.Certificate[0]); got != "two.example" {
		t.Fatalf("renewed certificate not picked up: %s", got)
	}
	if err := os.WriteFile(certFile, []byte("garbage"), 0o600); err != nil {
		t.Fatal(err)
	}
	transferTouch(t, later.Add(time.Minute), certFile, keyFile)
	cert, err = c.get(nil)
	if err != nil {
		t.Fatalf("a broken renewal must keep the old certificate: %v", err)
	}
	if got := transferCertName(t, cert.Certificate[0]); got != "two.example" {
		t.Fatalf("old certificate lost: %s", got)
	}
}

func TestTransferTicketAction(t *testing.T) {
	d := &commandDispatcher{}
	params := `{"name":"web-1","path":"/a/../a/b.txt","direction":"upload","origin":"https://panel.example"}`
	if _, err := d.executeTransfer("transfer.ticket", rawJSON(params)); err == nil {
		t.Fatal("transfers are off, the action must fail")
	}
	transferHub.port.Store(8443)
	t.Cleanup(func() { transferHub.port.Store(0) })
	bad := []string{
		`{"name":"web-1","path":"a.txt","direction":"upload","origin":"https://panel.example/x"}`,
		`{"name":"web-1","path":"a.txt","direction":"sideways","origin":"https://panel.example"}`,
		`{"name":"../web","path":"a.txt","direction":"upload","origin":"https://panel.example"}`,
		`{"name":"web-1","path":"/","direction":"upload","origin":"https://panel.example"}`,
		`{"name":"web-1","path":"a.txt","direction":"upload","origin":"https://panel.example","extra":1}`,
	}
	for _, p := range bad {
		if _, err := d.executeTransfer("transfer.ticket", rawJSON(p)); err == nil {
			t.Fatalf("expected an error for %s", p)
		}
	}
	data, err := d.executeTransfer("transfer.ticket", rawJSON(params))
	if err != nil {
		t.Fatal(err)
	}
	token, _ := data["token"].(string)
	if token == "" || data["port"] != 8443 {
		t.Fatalf("unexpected answer %v", data)
	}
	ticket, ok := transferHub.tickets.peek(token)
	if !ok || ticket.rel != "a/b.txt" || ticket.dir != transferUpload {
		t.Fatalf("unexpected ticket %+v", ticket)
	}
}

func TestTransferUploadReplacesASymlinkInsteadOfFollowingIt(t *testing.T) {
	srv, store, dir := transferTestSetup(t)
	victim := filepath.Join(filepath.Dir(dir), "victim.txt")
	if err := os.WriteFile(victim, []byte("keep"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(victim, filepath.Join(dir, "link.txt")); err != nil {
		t.Fatal(err)
	}
	token := transferIssue(t, store, transferUpload, "link.txt")
	resp, _ := transferDo(t, http.MethodPut, transferURL(srv, token), transferTestOrigin, "", strings.NewReader("new"))
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("status %d", resp.StatusCode)
	}
	if got, _ := os.ReadFile(victim); string(got) != "keep" {
		t.Fatalf("the upload wrote through the symlink: %q", got)
	}
	st, err := os.Lstat(filepath.Join(dir, "link.txt"))
	if err != nil || !st.Mode().IsRegular() {
		t.Fatalf("the link must be replaced by a regular file: %v", err)
	}
}
