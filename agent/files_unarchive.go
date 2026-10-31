package main

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"strings"
)

// Limits are variables so tests can lower them.
var (
	unarchiveMaxEntries       = 20000
	unarchiveMaxBytes   int64 = 2 << 30
)

var errArchiveLimit = errors.New("archive limit exceeded")

type unarchiveStats struct {
	budget  int64
	bytes   int64
	entries int
	files   int
	dirs    int
	skipped int
}

func archiveKind(name string) string {
	lower := strings.ToLower(name)
	switch {
	case strings.HasSuffix(lower, ".zip"):
		return "zip"
	case strings.HasSuffix(lower, ".tar.gz"), strings.HasSuffix(lower, ".tgz"):
		return "targz"
	}
	return ""
}

// safeEntryName returns the cleaned name. skip is true for "." (marker entries).
// Anything that would leave the root or be absolute is rejected.
func safeEntryName(raw string) (name string, skip bool, err error) {
	if strings.ContainsRune(raw, 0) {
		return "", false, fmt.Errorf("unsafe path in archive: %q", raw)
	}
	name = path.Clean(strings.ReplaceAll(raw, "\\", "/"))
	if name == "." {
		return "", true, nil
	}
	if !fs.ValidPath(name) {
		return "", false, fmt.Errorf("unsafe path in archive: %q", raw)
	}
	return name, false, nil
}

func (s *unarchiveStats) count() error {
	s.entries++
	if s.entries > unarchiveMaxEntries {
		return errArchiveLimit
	}
	return nil
}

func (s *unarchiveStats) writeFile(root *os.Root, target string, exec bool, src io.Reader) error {
	if err := bkMkdirAll(root, path.Dir(target)); err != nil {
		return err
	}
	mode := fs.FileMode(0o644)
	if exec {
		mode = 0o755
	}
	w, err := root.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode)
	if err != nil {
		return err
	}
	n, err := io.Copy(w, io.LimitReader(src, s.budget+1))
	s.budget -= n
	s.bytes += n
	if cerr := w.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		return err
	}
	if s.budget < 0 {
		_ = root.Remove(target)
		return errArchiveLimit
	}
	s.files++
	return nil
}

func unarchiveTarget(dest, name string) (string, error) {
	target := path.Join(dest, name)
	if len(target) > maxPathBytes {
		return "", fmt.Errorf("unsafe path in archive: %q", name)
	}
	return target, nil
}

func unzipInto(root *os.Root, f io.ReaderAt, size int64, dest string, st *unarchiveStats) error {
	zr, err := zip.NewReader(f, size)
	if err != nil {
		return fmt.Errorf("invalid archive: %w", err)
	}
	if len(zr.File) > unarchiveMaxEntries {
		return errArchiveLimit
	}
	var declared uint64
	for _, zf := range zr.File {
		if zf.UncompressedSize64 > uint64(unarchiveMaxBytes) {
			return errArchiveLimit
		}
		declared += zf.UncompressedSize64
		if declared > uint64(unarchiveMaxBytes) {
			return errArchiveLimit
		}
	}
	for _, zf := range zr.File {
		if err := st.count(); err != nil {
			return err
		}
		name, skip, err := safeEntryName(zf.Name)
		if err != nil {
			return err
		}
		if skip {
			continue
		}
		target, err := unarchiveTarget(dest, name)
		if err != nil {
			return err
		}
		mode := zf.Mode()
		switch {
		case zf.FileInfo().IsDir():
			if err := bkMkdirAll(root, target); err != nil {
				return err
			}
			st.dirs++
		case mode.IsRegular():
			rc, err := zf.Open()
			if err != nil {
				return fmt.Errorf("invalid archive: %w", err)
			}
			err = st.writeFile(root, target, mode&0o111 != 0, rc)
			rc.Close()
			if err != nil {
				return err
			}
		default:
			st.skipped++
		}
	}
	return nil
}

func untarInto(root *os.Root, r io.Reader, dest string, st *unarchiveStats) error {
	gz, err := gzip.NewReader(r)
	if err != nil {
		return fmt.Errorf("invalid archive: %w", err)
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return fmt.Errorf("invalid archive: %w", err)
		}
		if err := st.count(); err != nil {
			return err
		}
		name, skip, err := safeEntryName(hdr.Name)
		if err != nil {
			return err
		}
		if skip {
			continue
		}
		target, err := unarchiveTarget(dest, name)
		if err != nil {
			return err
		}
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := bkMkdirAll(root, target); err != nil {
				return err
			}
			st.dirs++
		case tar.TypeReg:
			if hdr.Size > st.budget {
				return errArchiveLimit
			}
			if err := st.writeFile(root, target, hdr.FileInfo().Mode()&0o111 != 0, tr); err != nil {
				return err
			}
		default:
			st.skipped++
		}
	}
}

// fileDecompress unpacks an archive in the server folder. to is the target folder,
// empty means: the folder where the archive is.
func fileDecompress(root *os.Root, archivePath, to string) (map[string]any, error) {
	rel, err := cleanPath(archivePath)
	if err != nil {
		return nil, err
	}
	if rel == "." {
		return nil, errors.New("invalid path")
	}
	kind := archiveKind(rel)
	if kind == "" {
		return nil, errors.New("unsupported archive type")
	}
	dest := path.Dir(rel)
	if strings.TrimSpace(to) != "" {
		if dest, err = cleanPath(to); err != nil {
			return nil, err
		}
	}
	f, err := root.Open(rel)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New(errNotRegularMsg)
	}
	if err := bkMkdirAll(root, dest); err != nil {
		return nil, err
	}
	st := &unarchiveStats{budget: unarchiveMaxBytes}
	if kind == "zip" {
		err = unzipInto(root, f, info.Size(), dest, st)
	} else {
		err = untarInto(root, f, dest, st)
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{"files": st.files, "dirs": st.dirs, "skipped": st.skipped, "bytes": st.bytes}, nil
}
