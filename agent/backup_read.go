package main

import (
	"encoding/base64"
	"errors"
	"io"
	"io/fs"
	"os"
)

// bkReadMax is the most the panel may ask for in one call. A reply has to stay below the
// message limit of the connection, and base64 adds a third.
const bkReadMax = 8 * 1024

// bkReadChunk returns up to length bytes of a backup archive from offset on, base64
// encoded, together with the size of the archive so the panel can announce the download.
// The archive path is built from a validated server name and backup id, symlinks are refused.
func bkReadChunk(archive string, offset int64, length int) (map[string]any, error) {
	if offset < 0 || length < 1 || length > bkReadMax {
		return nil, errors.New("invalid range")
	}
	info, err := os.Lstat(archive)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, errors.New("backup file not found")
		}
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("backup file not found")
	}
	if offset > info.Size() {
		return nil, errors.New("invalid range")
	}
	f, err := os.Open(archive)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	buf := make([]byte, length)
	n, err := f.ReadAt(buf, offset)
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, err
	}
	return map[string]any{
		"data": base64.StdEncoding.EncodeToString(buf[:n]),
		"size": info.Size(),
	}, nil
}
