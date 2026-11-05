package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"io"
	"io/fs"
	"log"
	"net"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

const (
	sftpMaxConns      = 64
	sftpHandshakeTime = 30 * time.Second
	sftpAuthTimeout   = 10 * time.Second
	sftpMaxUserLen    = 36
	sftpHostKeyName   = "sftp_host_key"
)

// sftpGrant is what the panel allows for one login.
type sftpGrant struct {
	Server string
	Write  bool
}

type sftpAuthFunc func(ctx context.Context, fingerprint, user string) (sftpGrant, error)

var errSFTPRejected = errors.New("rejected")

// ---- Asking the panel -------------------------------------------------------

type sftpAuthResult struct {
	OK     bool
	Server string
	Write  bool
}

// sftpAuthBroker sends sftp_auth frames over the panel connection of the current
// session and matches the sftp_auth_result frames to the waiting logins.
type sftpAuthBroker struct {
	mu      sync.Mutex
	send    func(map[string]any)
	pending map[string]chan sftpAuthResult
}

var sftpAuth = &sftpAuthBroker{pending: map[string]chan sftpAuthResult{}}

func (b *sftpAuthBroker) setSend(f func(map[string]any)) {
	b.mu.Lock()
	b.send = f
	b.mu.Unlock()
}

func (b *sftpAuthBroker) authorize(ctx context.Context, fingerprint, user string) (sftpGrant, error) {
	b.mu.Lock()
	send := b.send
	b.mu.Unlock()
	if send == nil {
		return sftpGrant{}, errors.New("the panel is not connected")
	}
	raw := make([]byte, 8)
	if _, err := rand.Read(raw); err != nil {
		return sftpGrant{}, err
	}
	id := hex.EncodeToString(raw)
	ch := make(chan sftpAuthResult, 1)
	b.mu.Lock()
	b.pending[id] = ch
	b.mu.Unlock()
	defer func() {
		b.mu.Lock()
		delete(b.pending, id)
		b.mu.Unlock()
	}()

	send(map[string]any{"type": "sftp_auth", "id": id, "fingerprint": fingerprint, "server": user})
	select {
	case res := <-ch:
		if !res.OK {
			return sftpGrant{}, errSFTPRejected
		}
		return sftpGrant{Server: res.Server, Write: res.Write}, nil
	case <-ctx.Done():
		return sftpGrant{}, ctx.Err()
	}
}

// notifyLogin tells the panel that a login finished, so it can audit it.
func (b *sftpAuthBroker) notifyLogin(fingerprint, server string) {
	b.mu.Lock()
	send := b.send
	b.mu.Unlock()
	if send == nil || fingerprint == "" {
		return
	}
	send(map[string]any{"type": "sftp_login", "fingerprint": fingerprint, "server": server})
}

func (b *sftpAuthBroker) resolve(id string, res sftpAuthResult) {
	b.mu.Lock()
	ch := b.pending[id]
	b.mu.Unlock()
	if ch == nil {
		return
	}
	select {
	case ch <- res:
	default:
	}
}

// ---- SSH server ---------------------------------------------------------------

type sftpServer struct {
	ctx      context.Context
	config   *ssh.ServerConfig
	auth     sftpAuthFunc
	dataPath func(name string) string
	limit    *ipLimiter
	slots    chan struct{}
}

func newSFTPServer(ctx context.Context, hostKey ssh.Signer, auth sftpAuthFunc, dataPath func(string) string) *sftpServer {
	s := &sftpServer{
		ctx:      ctx,
		auth:     auth,
		dataPath: dataPath,
		slots:    make(chan struct{}, sftpMaxConns),
		limit:    newIPLimiter(sftpMaxFails, sftpFailWindow),
	}
	s.config = &ssh.ServerConfig{
		MaxAuthTries:      3,
		ServerVersion:     "SSH-2.0-EpicWing",
		PublicKeyCallback: s.publicKey,
	}
	s.config.AddHostKey(hostKey)
	return s
}

func (s *sftpServer) publicKey(conn ssh.ConnMetadata, key ssh.PublicKey) (*ssh.Permissions, error) {
	ip := sftpRemoteIP(conn.RemoteAddr())
	if s.limit.blocked(ip) {
		return nil, errSFTPRejected
	}
	perms, err := s.checkKey(conn, key)
	if err != nil {
		s.limit.fail(ip)
	}
	return perms, err
}

func (s *sftpServer) checkKey(conn ssh.ConnMetadata, key ssh.PublicKey) (*ssh.Permissions, error) {
	user := conn.User()
	if user == "" || len(user) > sftpMaxUserLen {
		return nil, errSFTPRejected
	}
	ctx, cancel := context.WithTimeout(s.ctx, sftpAuthTimeout)
	defer cancel()
	grant, err := s.auth(ctx, ssh.FingerprintSHA256(key), user)
	if err != nil || !containerNameRe.MatchString(grant.Server) {
		return nil, errSFTPRejected
	}
	perms := &ssh.Permissions{Extensions: map[string]string{"server": grant.Server, "fp": ssh.FingerprintSHA256(key)}}
	if grant.Write {
		perms.Extensions["write"] = "1"
	}
	return perms, nil
}

func (s *sftpServer) serve(ln net.Listener) {
	go func() {
		<-s.ctx.Done()
		ln.Close()
	}()
	for {
		c, err := ln.Accept()
		if err != nil {
			if s.ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return
			}
			log.Printf("sftp: accept: %v", err)
			time.Sleep(time.Second)
			continue
		}
		select {
		case s.slots <- struct{}{}:
			go func() {
				defer func() { <-s.slots }()
				s.handleConn(c)
			}()
		default:
			c.Close()
		}
	}
}

func (s *sftpServer) handleConn(c net.Conn) {
	defer c.Close()
	if s.limit.blocked(sftpRemoteIP(c.RemoteAddr())) {
		return
	}
	if tc, ok := c.(*net.TCPConn); ok {
		tc.SetKeepAlive(true)
		tc.SetKeepAlivePeriod(30 * time.Second)
	}
	c.SetDeadline(time.Now().Add(sftpHandshakeTime))
	sconn, chans, reqs, err := ssh.NewServerConn(c, s.config)
	if err != nil {
		return
	}
	c.SetDeadline(time.Time{})
	defer sconn.Close()
	go ssh.DiscardRequests(reqs)

	perms := sconn.Permissions
	done := make(chan struct{})
	defer close(done)
	go s.watchGrant(sconn, perms.Extensions, done)
	sftpAuth.notifyLogin(perms.Extensions["fp"], perms.Extensions["server"])
	var wg sync.WaitGroup
	for nc := range chans {
		if nc.ChannelType() != "session" {
			nc.Reject(ssh.UnknownChannelType, "only sessions are supported")
			continue
		}
		ch, in, err := nc.Accept()
		if err != nil {
			continue
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			s.session(ch, in, perms)
		}()
	}
	wg.Wait()
}

func (s *sftpServer) session(ch ssh.Channel, in <-chan *ssh.Request, perms *ssh.Permissions) {
	defer ch.Close()
	for req := range in {
		var sub struct{ Name string }
		if req.Type != "subsystem" || ssh.Unmarshal(req.Payload, &sub) != nil || sub.Name != "sftp" {
			if req.WantReply {
				req.Reply(false, nil)
			}
			continue
		}
		root, err := os.OpenRoot(s.dataPath(perms.Extensions["server"]))
		if err != nil {
			req.Reply(false, nil)
			return
		}
		defer root.Close()
		req.Reply(true, nil)
		go ssh.DiscardRequests(in)

		fsys := &sftpFS{root: root, write: perms.Extensions["write"] == "1"}
		srv := sftp.NewRequestServer(ch, sftp.Handlers{
			FileGet: fsys, FilePut: fsys, FileCmd: fsys, FileList: fsys,
		})
		if err := srv.Serve(); err != nil && !errors.Is(err, io.EOF) {
			log.Printf("sftp: session ended: %v", err)
		}
		srv.Close()
		return
	}
}

// ---- File system inside the server folder ---------------------------------------

type sftpFS struct {
	root  *os.Root
	write bool
}

func (f *sftpFS) Fileread(r *sftp.Request) (io.ReaderAt, error) {
	rel, err := cleanPath(r.Filepath)
	if err != nil {
		return nil, err
	}
	info, err := f.root.Stat(rel)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New(errNotRegularMsg)
	}
	file, err := f.root.Open(rel)
	if err != nil {
		return nil, err
	}
	return file, nil
}

func (f *sftpFS) Filewrite(r *sftp.Request) (io.WriterAt, error) {
	if !f.write {
		return nil, sftp.ErrSSHFxPermissionDenied
	}
	rel, err := cleanPath(r.Filepath)
	if err != nil {
		return nil, err
	}
	if rel == "." {
		return nil, sftp.ErrSSHFxPermissionDenied
	}
	if info, err := f.root.Stat(rel); err == nil && !info.Mode().IsRegular() {
		return nil, errors.New(errNotRegularMsg)
	}
	pf := r.Pflags()
	flag := os.O_WRONLY
	if pf.Read {
		flag = os.O_RDWR
	}
	if pf.Creat {
		flag |= os.O_CREATE
	}
	if pf.Trunc {
		flag |= os.O_TRUNC
	}
	if pf.Excl {
		flag |= os.O_EXCL
	}
	file, err := f.root.OpenFile(rel, flag, 0o640)
	if err != nil {
		return nil, err
	}
	return file, nil
}

func (f *sftpFS) Filecmd(r *sftp.Request) error {
	if !f.write {
		return sftp.ErrSSHFxPermissionDenied
	}
	if r.Method == "Setstat" {
		// Clients set times and modes after an upload. Both are ignored on purpose.
		return nil
	}
	rel, err := cleanPath(r.Filepath)
	if err != nil {
		return err
	}
	if rel == "." {
		return sftp.ErrSSHFxPermissionDenied
	}
	switch r.Method {
	case "Mkdir":
		return f.root.Mkdir(rel, 0o750)
	case "Remove":
		info, err := f.root.Lstat(rel)
		if err != nil {
			return err
		}
		if info.IsDir() {
			return errors.New("is a directory")
		}
		return f.root.Remove(rel)
	case "Rmdir":
		info, err := f.root.Lstat(rel)
		if err != nil {
			return err
		}
		if !info.IsDir() {
			return errors.New("not a directory")
		}
		return f.root.Remove(rel)
	case "Rename", "PosixRename":
		to, err := cleanPath(r.Target)
		if err != nil {
			return err
		}
		if to == "." {
			return sftp.ErrSSHFxPermissionDenied
		}
		if r.Method == "Rename" {
			if _, err := f.root.Lstat(to); err == nil {
				return fs.ErrExist
			}
		}
		return renameInRoot(f.root, rel, to)
	default:
		return sftp.ErrSSHFxOpUnsupported
	}
}

func (f *sftpFS) Filelist(r *sftp.Request) (sftp.ListerAt, error) {
	rel, err := cleanPath(r.Filepath)
	if err != nil {
		return nil, err
	}
	switch r.Method {
	case "List":
		dir, err := f.root.Open(rel)
		if err != nil {
			return nil, err
		}
		defer dir.Close()
		entries, err := dir.ReadDir(-1)
		if err != nil {
			return nil, err
		}
		infos := make([]os.FileInfo, 0, len(entries))
		for _, e := range entries {
			if info, err := e.Info(); err == nil {
				infos = append(infos, info)
			}
		}
		sort.Slice(infos, func(i, j int) bool { return infos[i].Name() < infos[j].Name() })
		return sftpLister(infos), nil
	case "Stat":
		info, err := f.root.Stat(rel)
		if err != nil {
			return nil, err
		}
		return sftpLister{info}, nil
	default:
		return nil, sftp.ErrSSHFxOpUnsupported
	}
}

type sftpLister []os.FileInfo

func (l sftpLister) ListAt(ls []os.FileInfo, offset int64) (int, error) {
	if offset >= int64(len(l)) {
		return 0, io.EOF
	}
	n := copy(ls, l[offset:])
	if n < len(ls) {
		return n, io.EOF
	}
	return n, nil
}

// renameInRoot renames inside the server folder. os.Root has no Rename in Go 1.24, so
// both parent folders are opened through the root (symlinks cannot leave it) and
// renameat works on those handles. The last name is never followed.
func renameInRoot(root *os.Root, from, to string) error {
	oldDir, oldName := path.Split(from)
	newDir, newName := path.Split(to)
	if oldName == "" || newName == "" {
		return errors.New("invalid path")
	}
	od, err := openDirIn(root, oldDir)
	if err != nil {
		return err
	}
	defer od.Close()
	nd, err := openDirIn(root, newDir)
	if err != nil {
		return err
	}
	defer nd.Close()
	return syscall.Renameat(int(od.Fd()), oldName, int(nd.Fd()), newName)
}

func openDirIn(root *os.Root, dir string) (*os.File, error) {
	dir = strings.TrimSuffix(dir, "/")
	if dir == "" {
		dir = "."
	}
	return root.Open(dir)
}

// ---- Host key and start ------------------------------------------------------------

func loadOrCreateHostKey(file string) (ssh.Signer, error) {
	data, err := os.ReadFile(file)
	if err == nil {
		return ssh.ParsePrivateKey(data)
	}
	if !errors.Is(err, fs.ErrNotExist) {
		return nil, err
	}
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, err
	}
	block, err := ssh.MarshalPrivateKey(priv, "")
	if err != nil {
		return nil, err
	}
	f, err := os.OpenFile(file, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return nil, err
	}
	if err := pem.Encode(f, block); err != nil {
		f.Close()
		os.Remove(file)
		return nil, err
	}
	if err := f.Close(); err != nil {
		os.Remove(file)
		return nil, err
	}
	return ssh.NewSignerFromKey(priv)
}

// sftpSettings comes from policy.json. Without sftp_port the SFTP server stays off.
type sftpSettings struct {
	Port    int    `json:"sftp_port"`
	BindIP  string `json:"bind_ip"`
	DataDir string `json:"data_dir"`
}

func loadSFTPSettings() sftpSettings {
	var s sftpSettings
	data, err := os.ReadFile(filepath.Join(filepath.Dir(configPath()), policyFileName))
	if err != nil {
		return sftpSettings{}
	}
	if json.Unmarshal(data, &s) != nil {
		return sftpSettings{}
	}
	if s.DataDir == "" {
		s.DataDir = defaultDataDir
	}
	return s
}

var sftpOnce sync.Once

// startSFTP starts the SFTP server once per process. ctx is the process context.
func startSFTP(ctx context.Context) {
	sftpOnce.Do(func() {
		cfg := loadSFTPSettings()
		if cfg.Port == 0 {
			log.Print("sftp is off (no sftp_port in policy.json)")
			return
		}
		if cfg.Port < 1 || cfg.Port > 65535 || (cfg.BindIP != "" && !validBindIP(cfg.BindIP)) || !validDataDir(cfg.DataDir) {
			log.Print("invalid sftp settings in policy.json, sftp is off")
			return
		}
		hostKey, err := loadOrCreateHostKey(filepath.Join(filepath.Dir(cfg.DataDir), sftpHostKeyName))
		if err != nil {
			log.Printf("sftp host key: %v, sftp is off", err)
			return
		}
		ln, err := net.Listen("tcp", net.JoinHostPort(cfg.BindIP, strconv.Itoa(cfg.Port)))
		if err != nil {
			log.Printf("sftp listen: %v, sftp is off", err)
			return
		}
		srv := newSFTPServer(ctx, hostKey, sftpAuth.authorize, func(name string) string {
			return filepath.Join(cfg.DataDir, name)
		})
		log.Printf("sftp listening on %s", ln.Addr())
		go srv.serve(ln)
	})
}
