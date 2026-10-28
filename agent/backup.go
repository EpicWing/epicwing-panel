package main

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"
)

var (
	bkNameRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`)
	bkIDRe   = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
)

const bkMaxRunning = 2

type bkState struct {
	State  string `json:"state"` // running, ok, failed
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256,omitempty"`
	Error  string `json:"error,omitempty"`
}

type bkRegistry struct {
	mu   sync.Mutex
	jobs map[string]*bkState
	busy map[string]string
}

var bkJobs = &bkRegistry{jobs: map[string]*bkState{}, busy: map[string]string{}}

func (r *bkRegistry) start(name, key string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.busy[name]; ok {
		return errors.New("another backup operation is already running for this server")
	}
	if len(r.busy) >= bkMaxRunning {
		return errors.New("too many backup operations are running on this node")
	}
	r.busy[name] = key
	r.jobs[key] = &bkState{State: "running"}
	return nil
}

func (r *bkRegistry) finish(name, key string, st bkState) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.busy, name)
	r.jobs[key] = &st
}

func (r *bkRegistry) get(key string) (bkState, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if st, ok := r.jobs[key]; ok {
		return *st, true
	}
	return bkState{}, false
}

func (r *bkRegistry) isBusy(name string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	_, ok := r.busy[name]
	return ok
}

type bkRule struct {
	pattern  string
	negate   bool
	dirOnly  bool
	anchored bool
}

func parseBkRules(text string) []bkRule {
	var rules []bkRule
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		var r bkRule
		if strings.HasPrefix(line, "!") {
			r.negate = true
			line = line[1:]
		}
		if strings.HasSuffix(line, "/") {
			r.dirOnly = true
			line = strings.TrimRight(line, "/")
		}
		if strings.HasPrefix(line, "/") {
			r.anchored = true
			line = strings.TrimLeft(line, "/")
		}
		if line == "" {
			continue
		}
		if strings.Contains(line, "/") {
			r.anchored = true
		}
		r.pattern = line
		rules = append(rules, r)
	}
	return rules
}

// bkIgnored: die letzte passende Regel gewinnt. Ein ignorierter Ordner wird ganz übersprungen.
func bkIgnored(rules []bkRule, rel string, isDir bool) bool {
	ignored := false
	for _, r := range rules {
		if r.dirOnly && !isDir {
			continue
		}
		target := path.Base(rel)
		if r.anchored {
			target = rel
		}
		if ok, _ := path.Match(r.pattern, target); ok {
			ignored = !r.negate
		}
	}
	return ignored
}

type bkZero struct{}

func (bkZero) Read(p []byte) (int, error) {
	clear(p)
	return len(p), nil
}

func bkErrText(err error) string {
	msg := err.Error()
	if len(msg) > 500 {
		msg = strings.ToValidUTF8(msg[:500], "")
	}
	return msg
}

func bkCreate(src, dest, ignored string) (int64, string, error) {
	root, err := os.OpenRoot(src)
	if err != nil {
		return 0, "", err
	}
	defer root.Close()
	part := dest + ".part"
	out, err := os.OpenFile(part, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		return 0, "", err
	}
	done := false
	defer func() {
		if !done {
			out.Close()
			os.Remove(part)
		}
	}()
	h := sha256.New()
	gz := gzip.NewWriter(io.MultiWriter(out, h))
	tw := tar.NewWriter(gz)
	rules := parseBkRules(ignored)
	err = fs.WalkDir(root.FS(), ".", func(p string, d fs.DirEntry, werr error) error {
		if werr != nil {
			if errors.Is(werr, fs.ErrNotExist) {
				return nil
			}
			return werr
		}
		if p == "." {
			return nil
		}
		if bkIgnored(rules, p, d.IsDir()) {
			if d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		info, err := root.Lstat(p)
		if err != nil {
			if errors.Is(err, fs.ErrNotExist) {
				return nil
			}
			return err
		}
		if !info.Mode().IsRegular() && !info.IsDir() {
			return nil
		}
		var f *os.File
		if info.Mode().IsRegular() {
			f, err = root.Open(p)
			if err != nil {
				if errors.Is(err, fs.ErrNotExist) {
					return nil
				}
				return err
			}
			defer f.Close()
			if info, err = f.Stat(); err != nil {
				return err
			}
		}
		hdr, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		hdr.Name = p
		if info.IsDir() {
			hdr.Name += "/"
		}
		hdr.Uname, hdr.Gname = "", ""
		if err := tw.WriteHeader(hdr); err != nil {
			return err
		}
		if f == nil {
			return nil
		}
		n, err := io.Copy(tw, io.LimitReader(f, hdr.Size))
		if err != nil {
			return err
		}
		if n < hdr.Size {
			_, err = io.CopyN(tw, bkZero{}, hdr.Size-n)
		}
		return err
	})
	if err != nil {
		return 0, "", err
	}
	if err := tw.Close(); err != nil {
		return 0, "", err
	}
	if err := gz.Close(); err != nil {
		return 0, "", err
	}
	if err := out.Sync(); err != nil {
		return 0, "", err
	}
	if err := out.Close(); err != nil {
		return 0, "", err
	}
	if err := os.Rename(part, dest); err != nil {
		return 0, "", err
	}
	done = true
	st, err := os.Stat(dest)
	if err != nil {
		return 0, "", err
	}
	return st.Size(), hex.EncodeToString(h.Sum(nil)), nil
}

func bkSum(file string) (string, error) {
	f, err := os.Open(file)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func bkMkdirAll(root *os.Root, dir string) error {
	if dir == "." || dir == "" {
		return nil
	}
	cur := ""
	for _, seg := range strings.Split(dir, "/") {
		cur = path.Join(cur, seg)
		if err := root.Mkdir(cur, 0o755); err != nil && !errors.Is(err, fs.ErrExist) {
			return err
		}
	}
	return nil
}

// bkRestore entpackt in einen Staging-Ordner und tauscht ihn erst danach gegen den Server-Ordner.
func bkRestore(archive, base string) error {
	staging := base + ".restore-new"
	old := base + ".restore-old"
	if _, err := os.Lstat(base); errors.Is(err, fs.ErrNotExist) {
		if _, e := os.Lstat(old); e == nil {
			if err := os.Rename(old, base); err != nil {
				return err
			}
		}
	}
	baseInfo, err := os.Stat(base)
	if err != nil {
		return fmt.Errorf("server directory: %w", err)
	}
	if err := os.RemoveAll(staging); err != nil {
		return err
	}
	if err := os.RemoveAll(old); err != nil {
		return err
	}
	swapped := false
	defer func() {
		if !swapped {
			os.RemoveAll(staging)
		}
	}()
	if err := os.Mkdir(staging, baseInfo.Mode().Perm()); err != nil {
		return err
	}
	if uid, gid, ok := bkOwner(baseInfo); ok {
		if err := os.Lchown(staging, uid, gid); err != nil && !errors.Is(err, syscall.EPERM) {
			return err
		}
	}
	if err := os.Chmod(staging, baseInfo.Mode().Perm()); err != nil {
		return err
	}

	f, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	root, err := os.OpenRoot(staging)
	if err != nil {
		return err
	}
	defer root.Close()
	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		name := strings.TrimSuffix(hdr.Name, "/")
		if name == "." || !fs.ValidPath(name) {
			return fmt.Errorf("unsafe path in archive: %q", hdr.Name)
		}
		full := filepath.Join(staging, filepath.FromSlash(name))
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := bkMkdirAll(root, name); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := bkMkdirAll(root, path.Dir(name)); err != nil {
				return err
			}
			w, err := root.OpenFile(name, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
			if err != nil {
				return err
			}
			if _, err := io.Copy(w, tr); err != nil {
				w.Close()
				return err
			}
			if err := w.Close(); err != nil {
				return err
			}
		default:
			return fmt.Errorf("unsupported entry type in archive: %q", hdr.Name)
		}
		if err := os.Lchown(full, hdr.Uid, hdr.Gid); err != nil && !errors.Is(err, syscall.EPERM) {
			return err
		}
		if err := os.Chmod(full, fs.FileMode(hdr.Mode).Perm()); err != nil {
			return err
		}
		_ = os.Chtimes(full, hdr.ModTime, hdr.ModTime)
	}

	if err := os.Rename(base, old); err != nil {
		return err
	}
	if err := os.Rename(staging, base); err != nil {
		_ = os.Rename(old, base)
		return err
	}
	swapped = true
	if err := os.RemoveAll(old); err != nil {
		log.Printf("restore: could not remove %s: %v", old, err)
	}
	return nil
}

func bkOwner(fi os.FileInfo) (int, int, bool) {
	if st, ok := fi.Sys().(*syscall.Stat_t); ok {
		return int(st.Uid), int(st.Gid), true
	}
	return 0, 0, false
}

func bkWriteMeta(file string, st bkState) {
	b, err := json.Marshal(st)
	if err == nil {
		err = os.WriteFile(file, b, 0o600)
	}
	if err != nil {
		log.Printf("backup meta %s: %v", file, err)
	}
}

func bkStateMap(st bkState) map[string]any {
	return map[string]any{"state": st.State, "size": st.Size, "sha256": st.SHA256, "error": st.Error}
}

func (d *commandDispatcher) executeBackup(action string, raw json.RawMessage) (map[string]any, error) {
	var p struct {
		Name       string `json:"name"`
		ID         string `json:"id"`
		Ignored    string `json:"ignored"`
		SHA256     string `json:"sha256"`
		Kind       string `json:"kind"`
		Offset     int64  `json:"offset"`
		Length     int    `json:"length"`
		SourceName string `json:"source_name"`
		SourceID   string `json:"source_id"`
	}
	if err := decodeParams(raw, &p); err != nil {
		return nil, err
	}
	if !bkNameRe.MatchString(p.Name) {
		return nil, errors.New("invalid server name")
	}
	if !bkIDRe.MatchString(p.ID) {
		return nil, errors.New("invalid backup id")
	}
	dataDir := d.containers.policy.DataDir
	if !validDataDir(dataDir) {
		return nil, errors.New("the policy has no valid data_dir")
	}
	src := d.containers.dataPath(p.Name)
	dir := filepath.Join(filepath.Dir(filepath.Clean(dataDir)), "backups", p.Name)
	archive := filepath.Join(dir, p.ID+".tar.gz")
	meta := filepath.Join(dir, p.ID+".json")

	switch action {
	case "backup.create":
		if _, err := os.Stat(archive); err == nil {
			return nil, errors.New("this backup already exists")
		}
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return nil, err
		}
		key := "create:" + p.ID
		if err := bkJobs.start(p.Name, key); err != nil {
			return nil, err
		}
		go func() {
			size, sum, err := bkCreate(src, archive, p.Ignored)
			st := bkState{State: "ok", Size: size, SHA256: sum}
			if err != nil {
				st = bkState{State: "failed", Error: bkErrText(err)}
				log.Printf("backup %s of %s failed: %v", p.ID, p.Name, err)
			}
			bkWriteMeta(meta, st)
			bkJobs.finish(p.Name, key, st)
		}()
		return map[string]any{"state": "running"}, nil
	case "backup.restore":
		if _, err := os.Stat(archive); err != nil {
			return nil, errors.New("backup file not found")
		}
		key := "restore:" + p.ID
		if err := bkJobs.start(p.Name, key); err != nil {
			return nil, err
		}
		go func() {
			var err error
			if p.SHA256 != "" {
				var sum string
				if sum, err = bkSum(archive); err == nil && sum != p.SHA256 {
					err = errors.New("checksum mismatch, the backup file is damaged")
				}
			}
			if err == nil {
				err = bkRestore(archive, src)
			}
			st := bkState{State: "ok"}
			if err != nil {
				st = bkState{State: "failed", Error: bkErrText(err)}
				log.Printf("restore %s of %s failed: %v", p.ID, p.Name, err)
			}
			bkJobs.finish(p.Name, key, st)
		}()
		return map[string]any{"state": "running"}, nil
	case "backup.copy":
		if !bkNameRe.MatchString(p.SourceName) {
			return nil, errors.New("invalid source server name")
		}
		if !bkIDRe.MatchString(p.SourceID) {
			return nil, errors.New("invalid source backup id")
		}
		from := filepath.Join(filepath.Dir(filepath.Clean(dataDir)), "backups", p.SourceName, p.SourceID+".tar.gz")
		if _, err := os.Stat(from); err != nil {
			return nil, errors.New("backup file not found")
		}
		if _, err := os.Stat(archive); err == nil {
			return nil, errors.New("this backup already exists")
		}
		if bkJobs.isBusy(p.SourceName) {
			return nil, errors.New("a backup operation is running for this server")
		}
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return nil, err
		}
		key := "create:" + p.ID
		if err := bkJobs.start(p.Name, key); err != nil {
			return nil, err
		}
		go func() {
			size, sum, err := bkCopy(from, archive, p.SHA256)
			st := bkState{State: "ok", Size: size, SHA256: sum}
			if err != nil {
				st = bkState{State: "failed", Error: bkErrText(err)}
				log.Printf("backup copy %s of %s failed: %v", p.ID, p.Name, err)
			}
			bkWriteMeta(meta, st)
			bkJobs.finish(p.Name, key, st)
		}()
		return map[string]any{"state": "running"}, nil
	case "backup.read":
		return bkReadChunk(archive, p.Offset, p.Length)
	case "backup.status":
		kind := p.Kind
		if kind == "" {
			kind = "create"
		}
		if st, ok := bkJobs.get(kind + ":" + p.ID); ok {
			return bkStateMap(st), nil
		}
		if kind == "restore" {
			return map[string]any{"state": "unknown", "error": "the agent restarted, the result of the restore is unknown"}, nil
		}
		if b, err := os.ReadFile(meta); err == nil {
			var st bkState
			if json.Unmarshal(b, &st) == nil {
				return bkStateMap(st), nil
			}
		}
		if _, err := os.Stat(archive + ".part"); err == nil {
			return bkStateMap(bkState{State: "failed", Error: "interrupted"}), nil
		}
		if _, err := os.Stat(archive); err == nil {
			return bkStateMap(bkState{State: "failed", Error: "interrupted"}), nil
		}
		return nil, errors.New("backup not found")
	case "backup.delete":
		if bkJobs.isBusy(p.Name) {
			return nil, errors.New("a backup operation is running for this server")
		}
		for _, f := range []string{archive, archive + ".part", meta} {
			if err := os.Remove(f); err != nil && !errors.Is(err, fs.ErrNotExist) {
				return nil, err
			}
		}
		return map[string]any{}, nil
	default:
		return nil, fmt.Errorf("unknown action %q", action)
	}
}

var _ = time.Second

// bkCopy kopiert ein fertiges Archiv und prüft dabei die Prüfsumme. Die Zieldatei
// erscheint erst, wenn alles stimmt.
func bkCopy(src, dest, want string) (int64, string, error) {
	in, err := os.Open(src)
	if err != nil {
		return 0, "", err
	}
	defer in.Close()
	part := dest + ".part"
	out, err := os.OpenFile(part, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return 0, "", err
	}
	h := sha256.New()
	size, err := io.Copy(io.MultiWriter(out, h), in)
	if err == nil {
		err = out.Sync()
	}
	if cerr := out.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		os.Remove(part)
		return 0, "", err
	}
	sum := hex.EncodeToString(h.Sum(nil))
	if want != "" && sum != want {
		os.Remove(part)
		return 0, "", errors.New("checksum mismatch, the source backup file is damaged")
	}
	if err := os.Rename(part, dest); err != nil {
		os.Remove(part)
		return 0, "", err
	}
	return size, sum, nil
}
