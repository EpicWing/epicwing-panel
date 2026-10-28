package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"log"
	"mime"
	"net"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

const (
	transferTicketTTL  = 60 * time.Second
	transferMaxTickets = 256
	transferMaxActive  = 8
	transferMaxUpload  = int64(16) << 30
	transferStalePart  = time.Hour
	transferURLPrefix  = "/transfer/"
	transferUpload     = "upload"
	transferDownload   = "download"
	transferPartSuffix = ".part"
)

// transferTicket allows exactly one transfer of one file in one direction.
type transferTicket struct {
	name    string
	rel     string
	dir     string
	origin  string
	expires time.Time
}

// transferTicketStore keeps one-time tickets in memory. Only hashes are stored.
type transferTicketStore struct {
	mu    sync.Mutex
	items map[string]transferTicket
	now   func() time.Time
}

func newTransferTicketStore() *transferTicketStore {
	return &transferTicketStore{items: map[string]transferTicket{}, now: time.Now}
}

func transferKey(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

func (s *transferTicketStore) purgeLocked() {
	now := s.now()
	for key, t := range s.items {
		if !t.expires.After(now) {
			delete(s.items, key)
		}
	}
}

func (s *transferTicketStore) issue(t transferTicket) (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	token := base64.RawURLEncoding.EncodeToString(raw)
	s.mu.Lock()
	defer s.mu.Unlock()
	s.purgeLocked()
	if len(s.items) >= transferMaxTickets {
		return "", errors.New("too many open transfer tickets")
	}
	t.expires = s.now().Add(transferTicketTTL)
	s.items[transferKey(token)] = t
	return token, nil
}

// peek looks at a ticket without using it up.
func (s *transferTicketStore) peek(token string) (transferTicket, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.purgeLocked()
	t, ok := s.items[transferKey(token)]
	return t, ok
}

// redeem returns the ticket and removes it.
func (s *transferTicketStore) redeem(token string) (transferTicket, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.purgeLocked()
	key := transferKey(token)
	t, ok := s.items[key]
	if ok {
		delete(s.items, key)
	}
	return t, ok
}

type transferServer struct {
	tickets  *transferTicketStore
	dataPath func(string) string
	slots    chan struct{}
}

func newTransferServer(tickets *transferTicketStore, dataPath func(string) string) *transferServer {
	return &transferServer{tickets: tickets, dataPath: dataPath, slots: make(chan struct{}, transferMaxActive)}
}

func (s *transferServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h := w.Header()
	h.Set("Cache-Control", "no-store")
	h.Set("X-Content-Type-Options", "nosniff")
	h.Add("Vary", "Origin")
	token, ok := strings.CutPrefix(r.URL.Path, transferURLPrefix)
	if !ok || token == "" || strings.Contains(token, "/") {
		http.NotFound(w, r)
		return
	}
	switch r.Method {
	case http.MethodOptions:
		s.preflight(w, r, token)
	case http.MethodGet, http.MethodHead:
		s.download(w, r, token)
	case http.MethodPut:
		s.upload(w, r, token)
	default:
		h.Set("Allow", "GET, HEAD, PUT, OPTIONS")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (s *transferServer) acquire(w http.ResponseWriter) bool {
	select {
	case s.slots <- struct{}{}:
		return true
	default:
		http.Error(w, "too many transfers", http.StatusServiceUnavailable)
		return false
	}
}

func (s *transferServer) release() { <-s.slots }

// claim checks direction and origin first and only then uses the ticket up,
// so a wrong request cannot burn a valid ticket.
func (s *transferServer) claim(w http.ResponseWriter, r *http.Request, token, dir string) (transferTicket, bool) {
	deny := func() (transferTicket, bool) {
		http.Error(w, "invalid or expired ticket", http.StatusForbidden)
		return transferTicket{}, false
	}
	t, ok := s.tickets.peek(token)
	origin := r.Header.Get("Origin")
	if !ok || t.dir != dir || (origin != "" && origin != t.origin) || (dir == transferUpload && origin == "") {
		return deny()
	}
	if t, ok = s.tickets.redeem(token); !ok {
		return deny()
	}
	if origin != "" {
		w.Header().Set("Access-Control-Allow-Origin", origin)
	}
	return t, true
}

func (s *transferServer) preflight(w http.ResponseWriter, r *http.Request, token string) {
	t, ok := s.tickets.peek(token)
	origin := r.Header.Get("Origin")
	if !ok || t.dir != transferUpload || origin == "" || origin != t.origin ||
		r.Header.Get("Access-Control-Request-Method") != http.MethodPut {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	h := w.Header()
	h.Set("Access-Control-Allow-Origin", origin)
	h.Set("Access-Control-Allow-Methods", "PUT")
	h.Set("Access-Control-Allow-Headers", "Content-Type")
	h.Set("Access-Control-Max-Age", "60")
	w.WriteHeader(http.StatusNoContent)
}

func transferFail(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, fs.ErrNotExist):
		http.Error(w, "file not found", http.StatusNotFound)
	case errors.Is(err, fs.ErrExist):
		http.Error(w, "file exists", http.StatusConflict)
	case strings.Contains(err.Error(), "escapes"):
		http.Error(w, "invalid path", http.StatusBadRequest)
	default:
		http.Error(w, "the file operation failed", http.StatusInternalServerError)
	}
}

func transferDisposition(name string) string {
	if v := mime.FormatMediaType("attachment", map[string]string{"filename": name}); v != "" {
		return v
	}
	return "attachment"
}

func (s *transferServer) download(w http.ResponseWriter, r *http.Request, token string) {
	if !s.acquire(w) {
		return
	}
	defer s.release()
	t, ok := s.claim(w, r, token, transferDownload)
	if !ok {
		return
	}
	root, err := os.OpenRoot(s.dataPath(t.name))
	if err != nil {
		http.Error(w, "server data directory not available", http.StatusServiceUnavailable)
		return
	}
	defer root.Close()
	f, err := root.OpenFile(t.rel, os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		transferFail(w, err)
		return
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		transferFail(w, err)
		return
	}
	if !st.Mode().IsRegular() {
		http.Error(w, errNotRegularMsg, http.StatusConflict)
		return
	}
	h := w.Header()
	h.Set("Content-Type", "application/octet-stream")
	h.Set("Content-Disposition", transferDisposition(path.Base(t.rel)))
	http.ServeContent(w, r, "", st.ModTime(), f)
}

func (s *transferServer) upload(w http.ResponseWriter, r *http.Request, token string) {
	if r.ContentLength < 0 {
		http.Error(w, "length required", http.StatusLengthRequired)
		return
	}
	if r.ContentLength > transferMaxUpload {
		http.Error(w, "file too large", http.StatusRequestEntityTooLarge)
		return
	}
	if !s.acquire(w) {
		return
	}
	defer s.release()
	t, ok := s.claim(w, r, token, transferUpload)
	if !ok {
		return
	}
	if t.rel == "." {
		http.Error(w, "invalid path", http.StatusBadRequest)
		return
	}
	root, err := os.OpenRoot(s.dataPath(t.name))
	if err != nil {
		http.Error(w, "server data directory not available", http.StatusServiceUnavailable)
		return
	}
	defer root.Close()
	if st, err := root.Stat(t.rel); err == nil && !st.Mode().IsRegular() {
		http.Error(w, errNotRegularMsg, http.StatusConflict)
		return
	}
	part := t.rel + transferPartSuffix
	if st, err := root.Stat(part); err == nil && time.Since(st.ModTime()) > transferStalePart {
		_ = root.Remove(part)
	}
	f, err := root.OpenFile(part, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		if errors.Is(err, fs.ErrExist) {
			http.Error(w, "an upload of this file is already running", http.StatusConflict)
			return
		}
		transferFail(w, err)
		return
	}
	n, copyErr := io.Copy(f, r.Body)
	closeErr := f.Close()
	if copyErr != nil || closeErr != nil || n != r.ContentLength {
		_ = root.Remove(part)
		if copyErr == nil && closeErr == nil {
			http.Error(w, "incomplete upload", http.StatusBadRequest)
		} else {
			http.Error(w, "the upload failed", http.StatusInternalServerError)
		}
		return
	}
	err = transferReplace(root, part, t.rel)
	if err != nil {
		_ = root.Remove(part)
		transferFail(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// transferCertReloader loads the certificate again when the files change,
// so a renewal needs no restart. A broken new file keeps the old certificate.
type transferCertReloader struct {
	certFile string
	keyFile  string
	mu       sync.Mutex
	cert     *tls.Certificate
	certMod  time.Time
	keyMod   time.Time
}

func (c *transferCertReloader) get(*tls.ClientHelloInfo) (*tls.Certificate, error) {
	cs, certErr := os.Stat(c.certFile)
	ks, keyErr := os.Stat(c.keyFile)
	c.mu.Lock()
	defer c.mu.Unlock()
	if certErr == nil && keyErr == nil &&
		(c.cert == nil || !cs.ModTime().Equal(c.certMod) || !ks.ModTime().Equal(c.keyMod)) {
		pair, err := tls.LoadX509KeyPair(c.certFile, c.keyFile)
		if err != nil {
			if c.cert == nil {
				return nil, err
			}
			log.Printf("transfer certificate reload failed, keeping the old one: %v", err)
			c.certMod, c.keyMod = cs.ModTime(), ks.ModTime()
			return c.cert, nil
		}
		c.cert = &pair
		c.certMod, c.keyMod = cs.ModTime(), ks.ModTime()
	}
	if c.cert == nil {
		return nil, errors.New("no certificate loaded")
	}
	return c.cert, nil
}

// transferSettings comes from policy.json. Without https_port direct transfers stay off.
type transferSettings struct {
	Port    int    `json:"https_port"`
	Cert    string `json:"tls_cert"`
	Key     string `json:"tls_key"`
	BindIP  string `json:"bind_ip"`
	DataDir string `json:"data_dir"`
}

func loadTransferSettings() transferSettings {
	var s transferSettings
	data, err := os.ReadFile(filepath.Join(filepath.Dir(configPath()), policyFileName))
	if err != nil || json.Unmarshal(data, &s) != nil {
		return transferSettings{}
	}
	if s.DataDir == "" {
		s.DataDir = defaultDataDir
	}
	return s
}

type transferState struct {
	tickets *transferTicketStore
	port    atomic.Int32
}

var transferHub = &transferState{tickets: newTransferTicketStore()}

var transferOnce sync.Once

// startTransfer starts the HTTPS endpoint once per process. ctx is the process context.
func startTransfer(ctx context.Context) {
	transferOnce.Do(func() {
		cfg := loadTransferSettings()
		if cfg.Port == 0 {
			log.Print("direct transfers are off (no https_port in policy.json)")
			return
		}
		if cfg.Port < 1 || cfg.Port > 65535 || (cfg.BindIP != "" && !validBindIP(cfg.BindIP)) ||
			!validDataDir(cfg.DataDir) || cfg.Cert == "" || cfg.Key == "" {
			log.Print("invalid transfer settings in policy.json, direct transfers are off")
			return
		}
		reloader := &transferCertReloader{certFile: cfg.Cert, keyFile: cfg.Key}
		if _, err := reloader.get(nil); err != nil {
			log.Printf("transfer certificate: %v, direct transfers are off", err)
			return
		}
		ln, err := net.Listen("tcp", net.JoinHostPort(cfg.BindIP, strconv.Itoa(cfg.Port)))
		if err != nil {
			log.Printf("transfer listen: %v, direct transfers are off", err)
			return
		}
		srv := &http.Server{
			Handler: newTransferServer(transferHub.tickets, func(name string) string {
				return filepath.Join(cfg.DataDir, name)
			}),
			TLSConfig:         &tls.Config{MinVersion: tls.VersionTLS12, GetCertificate: reloader.get},
			ReadHeaderTimeout: 10 * time.Second,
			IdleTimeout:       60 * time.Second,
			ErrorLog:          log.New(io.Discard, "", 0),
		}
		transferHub.port.Store(int32(cfg.Port))
		log.Printf("direct transfers listening on %s", ln.Addr())
		go func() {
			<-ctx.Done()
			_ = srv.Close()
		}()
		go func() {
			if err := srv.ServeTLS(ln, "", ""); err != nil && !errors.Is(err, http.ErrServerClosed) {
				log.Printf("transfer server: %v", err)
				transferHub.port.Store(0)
			}
		}()
	})
}

type transferParams struct {
	Name      string `json:"name"`
	Path      string `json:"path"`
	Direction string `json:"direction"`
	Origin    string `json:"origin"`
}

func validTransferOrigin(o string) bool {
	if len(o) > 255 {
		return false
	}
	u, err := url.Parse(o)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" ||
		u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" {
		return false
	}
	return u.Scheme+"://"+u.Host == o
}

// executeTransfer handles transfer.ticket: the panel asks for a one-time ticket.
func (d *commandDispatcher) executeTransfer(action string, raw json.RawMessage) (map[string]any, error) {
	if action != "transfer.ticket" {
		return nil, errors.New("unknown action " + strconv.Quote(action))
	}
	var p transferParams
	if err := decodeParams(raw, &p); err != nil {
		return nil, err
	}
	port := int(transferHub.port.Load())
	if port == 0 {
		return nil, errors.New("transfers are not enabled on this node")
	}
	if !containerNameRe.MatchString(p.Name) {
		return nil, errors.New("invalid container name")
	}
	if p.Direction != transferUpload && p.Direction != transferDownload {
		return nil, errors.New("invalid direction")
	}
	if !validTransferOrigin(p.Origin) {
		return nil, errors.New("invalid origin")
	}
	rel, err := cleanPath(p.Path)
	if err != nil {
		return nil, err
	}
	if rel == "." {
		return nil, errors.New("invalid path")
	}
	if p.Direction == transferDownload {
		root, err := os.OpenRoot(d.containers.dataPath(p.Name))
		if err != nil {
			return nil, errors.New("server data directory not available")
		}
		defer root.Close()
		st, err := root.Stat(rel)
		if err != nil {
			return nil, err
		}
		if !st.Mode().IsRegular() {
			return nil, errors.New(errNotRegularMsg)
		}
	}
	token, err := transferHub.tickets.issue(transferTicket{name: p.Name, rel: rel, dir: p.Direction, origin: p.Origin})
	if err != nil {
		return nil, err
	}
	return map[string]any{"token": token, "port": port, "expires_in": int(transferTicketTTL.Seconds())}, nil
}

// transferReplace renames from over to in one step, so an existing file is never missing
// in between. A symlink as target is replaced and not followed.
func transferReplace(root *os.Root, from, to string) error {
	fa, err := root.Open(path.Dir(from))
	if err != nil {
		return err
	}
	defer fa.Close()
	fb, err := root.Open(path.Dir(to))
	if err != nil {
		return err
	}
	defer fb.Close()
	return syscall.Renameat(int(fa.Fd()), path.Base(from), int(fb.Fd()), path.Base(to))
}
