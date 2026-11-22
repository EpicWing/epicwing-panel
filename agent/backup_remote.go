package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"time"
)

// Backups in object storage. The panel keeps the S3 keys and only sends presigned URLs,
// so a node can upload or download exactly one file and nothing else.

const (
	bkMaxParts     = 10000
	bkPartRetries  = 3
	bkPartTimeout  = time.Hour
	bkFetchTimeout = 12 * time.Hour
)

var (
	// Uploads and downloads do not touch the server data, so they must not block a start.
	bkTransfers  = &bkRegistry{jobs: map[string]*bkState{}, busy: map[string]string{}}
	bkRetryDelay = 2 * time.Second
	bkS3CodeRe   = regexp.MustCompile(`<Code>([A-Za-z0-9.]{1,64})</Code>`)
)

// bkClient never follows redirects. Presigned storage URLs do not need them, and
// following one could send the request to a different, possibly internal, address.
var bkClient = &http.Client{
	CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	},
}

func bkValidURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" {
		return errors.New("invalid storage url")
	}
	return nil
}

// bkHTTPErr drops the URL from an error, it contains the signature.
func bkHTTPErr(err error) error {
	var ue *url.Error
	if errors.As(err, &ue) {
		err = ue.Err
	}
	return fmt.Errorf("the storage is not reachable: %v", err)
}

func bkStatusErr(resp *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if m := bkS3CodeRe.FindSubmatch(body); m != nil {
		return fmt.Errorf("the storage answered HTTP %d (%s)", resp.StatusCode, m[1])
	}
	return fmt.Errorf("the storage answered HTTP %d", resp.StatusCode)
}

func bkPutPart(rawURL string, body io.Reader, size int64) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), bkPartTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, rawURL, body)
	if err != nil {
		return "", errors.New("invalid storage url")
	}
	req.ContentLength = size
	resp, err := bkClient.Do(req)
	if err != nil {
		return "", bkHTTPErr(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", bkStatusErr(resp)
	}
	io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<20))
	tag := resp.Header.Get("ETag")
	if tag == "" {
		return "", errors.New("the storage sent no ETag")
	}
	return tag, nil
}

// bkUpload sends the archive in parts of partSize bytes, one presigned URL per part,
// and returns the ETags in order. A failed part is tried again a few times.
func bkUpload(archive string, partSize int64, urls []string) ([]string, error) {
	f, err := os.Open(archive)
	if err != nil {
		return nil, errors.New("backup file not found")
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil {
		return nil, err
	}
	size := fi.Size()
	if partSize <= 0 {
		return nil, errors.New("invalid part size")
	}
	need := (size + partSize - 1) / partSize
	if need == 0 {
		need = 1
	}
	if int64(len(urls)) != need {
		return nil, fmt.Errorf("the panel sent %d upload links, %d are needed", len(urls), need)
	}
	etags := make([]string, 0, len(urls))
	for i, u := range urls {
		offset := int64(i) * partSize
		length := min(partSize, size-offset)
		var tag string
		for attempt := 1; attempt <= bkPartRetries; attempt++ {
			tag, err = bkPutPart(u, io.NewSectionReader(f, offset, length), length)
			if err == nil {
				break
			}
			if attempt < bkPartRetries {
				time.Sleep(time.Duration(attempt) * bkRetryDelay)
			}
		}
		if err != nil {
			return nil, fmt.Errorf("part %d of %d: %w", i+1, len(urls), err)
		}
		etags = append(etags, tag)
	}
	return etags, nil
}

// bkFetch downloads an archive from a presigned URL and checks its checksum. The target
// file only appears when everything is right.
func bkFetch(rawURL, dest, want string) (int64, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), bkFetchTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return 0, "", errors.New("invalid storage url")
	}
	resp, err := bkClient.Do(req)
	if err != nil {
		return 0, "", bkHTTPErr(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, "", bkStatusErr(resp)
	}
	part := dest + ".part"
	out, err := os.OpenFile(part, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return 0, "", err
	}
	h := sha256.New()
	size, err := io.Copy(io.MultiWriter(out, h), resp.Body)
	if err != nil {
		err = bkHTTPErr(err)
	} else {
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
		return 0, "", errors.New("checksum mismatch, the backup in the storage is damaged")
	}
	if err := os.Rename(part, dest); err != nil {
		os.Remove(part)
		return 0, "", err
	}
	return size, sum, nil
}
