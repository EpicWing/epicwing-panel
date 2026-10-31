package main

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"sort"
	"strings"
	"syscall"
)

const (
	maxFileChunk     = 512 * 1024
	maxListBytes     = 10 * 1024
	maxListEntries   = 200
	maxRemoveDepth   = 64
	maxPathBytes     = 1024
	maxWriteOffset   = 1 << 30
	errNotRegularMsg = "not a regular file"
)

type fileParams struct {
	Name      string `json:"name"`
	Path      string `json:"path"`
	To        string `json:"to"`
	Offset    int64  `json:"offset"`
	Length    int    `json:"length"`
	Data      string `json:"data"`
	Create    bool   `json:"create"`
	Truncate  bool   `json:"truncate"`
	Recursive bool   `json:"recursive"`
}

// cleanPath macht aus einem Panel-Pfad einen relativen Pfad im Server-Ordner.
// A leading "/" and ".." are caught as plain text at the root,
// symlinks are resolved by os.Root only inside the root.
func cleanPath(p string) (string, error) {
	if len(p) > maxPathBytes || strings.ContainsRune(p, 0) {
		return "", errors.New("invalid path")
	}
	c := strings.TrimPrefix(path.Clean("/"+p), "/")
	if c == "" {
		c = "."
	}
	return c, nil
}

func (d *commandDispatcher) executeFile(action string, raw json.RawMessage) (map[string]any, error) {
	var p fileParams
	if err := decodeParams(raw, &p); err != nil {
		return nil, err
	}
	if !containerNameRe.MatchString(p.Name) {
		return nil, errors.New("invalid container name")
	}
	root, err := os.OpenRoot(d.containers.dataPath(p.Name))
	if err != nil {
		return nil, errors.New("server data directory not available")
	}
	defer root.Close()
	switch action {
	case "file.list":
		return fileList(root, p.Path, int(p.Offset))
	case "file.read":
		return fileRead(root, p.Path, p.Offset, p.Length)
	case "file.write":
		return nil, fileWrite(root, p.Path, p.Offset, p.Data, p.Create, p.Truncate)
	case "file.mkdir":
		rel, err := cleanPath(p.Path)
		if err != nil {
			return nil, err
		}
		return nil, root.Mkdir(rel, 0o755)
	case "file.rename":
		return nil, fileRename(root, p.Path, p.To)
	case "file.decompress":
		return fileDecompress(root, p.Path, p.To)
	case "file.delete":
		return nil, fileDelete(root, p.Path, p.Recursive)
	default:
		return nil, fmt.Errorf("unknown action %q", action)
	}
}

func fileList(root *os.Root, p string, offset int) (map[string]any, error) {
	rel, err := cleanPath(p)
	if err != nil {
		return nil, err
	}
	f, err := root.Open(rel)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	infos, err := f.ReadDir(-1)
	if err != nil {
		return nil, err
	}
	sort.Slice(infos, func(i, j int) bool {
		if infos[i].IsDir() != infos[j].IsDir() {
			return infos[i].IsDir()
		}
		return infos[i].Name() < infos[j].Name()
	})
	if offset < 0 || offset > len(infos) {
		offset = len(infos)
	}
	entries := []map[string]any{}
	size, next := 0, -1
	for i := offset; i < len(infos); i++ {
		info, err := infos[i].Info()
		if err != nil {
			continue
		}
		item := map[string]any{
			"name":  infos[i].Name(),
			"dir":   infos[i].IsDir(),
			"link":  infos[i].Type()&fs.ModeSymlink != 0,
			"size":  info.Size(),
			"mtime": info.ModTime().Unix(),
		}
		enc, _ := json.Marshal(item)
		if len(entries) > 0 && (size+len(enc) > maxListBytes || len(entries) >= maxListEntries) {
			next = i
			break
		}
		size += len(enc) + 1
		entries = append(entries, item)
	}
	return map[string]any{"entries": entries, "total": len(infos), "next": next}, nil
}

func fileRead(root *os.Root, p string, offset int64, length int) (map[string]any, error) {
	rel, err := cleanPath(p)
	if err != nil {
		return nil, err
	}
	if offset < 0 {
		return nil, errors.New("invalid offset")
	}
	if length <= 0 || length > maxFileChunk {
		length = maxFileChunk
	}
	f, err := root.OpenFile(rel, os.O_RDONLY|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !st.Mode().IsRegular() {
		return nil, errors.New(errNotRegularMsg)
	}
	buf := make([]byte, length)
	n, err := f.ReadAt(buf, offset)
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, err
	}
	return map[string]any{
		"data": base64.StdEncoding.EncodeToString(buf[:n]),
		"size": st.Size(),
		"eof":  offset+int64(n) >= st.Size(),
	}, nil
}

func fileWrite(root *os.Root, p string, offset int64, b64 string, create, truncate bool) error {
	rel, err := cleanPath(p)
	if err != nil {
		return err
	}
	if rel == "." {
		return errors.New("invalid path")
	}
	if offset < 0 || offset > maxWriteOffset {
		return errors.New("invalid offset")
	}
	data, err := base64.StdEncoding.DecodeString(b64)
	if err != nil || len(data) > maxFileChunk {
		return errors.New("invalid data")
	}
	flags := os.O_WRONLY | syscall.O_NONBLOCK
	if create {
		flags |= os.O_CREATE
	}
	if truncate {
		flags |= os.O_TRUNC
	}
	f, err := root.OpenFile(rel, flags, 0o644)
	if err != nil {
		return err
	}
	st, err := f.Stat()
	if err != nil {
		f.Close()
		return err
	}
	if !st.Mode().IsRegular() {
		f.Close()
		return errors.New(errNotRegularMsg)
	}
	if _, err := f.WriteAt(data, offset); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

func fileRename(root *os.Root, from, to string) error {
	a, err := cleanPath(from)
	if err != nil {
		return err
	}
	b, err := cleanPath(to)
	if err != nil {
		return err
	}
	if a == "." || b == "." {
		return errors.New("invalid path")
	}
	if _, err := root.Lstat(b); err == nil {
		return errors.New("target already exists")
	}
	fa, err := root.Open(path.Dir(a))
	if err != nil {
		return err
	}
	defer fa.Close()
	fb, err := root.Open(path.Dir(b))
	if err != nil {
		return err
	}
	defer fb.Close()
	if err := syscall.Renameat(int(fa.Fd()), path.Base(a), int(fb.Fd()), path.Base(b)); err != nil {
		return fmt.Errorf("rename: %w", err)
	}
	return nil
}

func fileDelete(root *os.Root, p string, recursive bool) error {
	rel, err := cleanPath(p)
	if err != nil {
		return err
	}
	if rel == "." {
		return errors.New("cannot delete the server root")
	}
	st, err := root.Lstat(rel)
	if err != nil {
		return err
	}
	if !st.IsDir() || !recursive {
		return root.Remove(rel)
	}
	return removeTree(root, rel, 0)
}

func removeTree(root *os.Root, rel string, depth int) error {
	if depth > maxRemoveDepth {
		return errors.New("directory nesting too deep")
	}
	f, err := root.Open(rel)
	if err != nil {
		return err
	}
	entries, err := f.ReadDir(-1)
	f.Close()
	if err != nil {
		return err
	}
	for _, e := range entries {
		child := path.Join(rel, e.Name())
		if e.IsDir() {
			err = removeTree(root, child, depth+1)
		} else {
			err = root.Remove(child)
		}
		if err != nil {
			return err
		}
	}
	return root.Remove(rel)
}
