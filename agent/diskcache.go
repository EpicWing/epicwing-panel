package main

import (
	"sync"
	"time"
)

// du -sb walks the whole data folder, so it runs at most once per minute per container.
const diskCacheTTL = 60 * time.Second

type diskSample struct {
	bytes int64
	at    time.Time
}

var diskCache = struct {
	sync.Mutex
	m map[string]diskSample
}{m: map[string]diskSample{}}

func (c *consoleManager) diskUsage(name string) int64 {
	diskCache.Lock()
	cached, ok := diskCache.m[name]
	diskCache.Unlock()
	if ok && time.Since(cached.at) < diskCacheTTL {
		return cached.bytes
	}
	value := c.measureDisk(name)
	if value == 0 && ok {
		// A failed measurement must not overwrite the last known value.
		value = cached.bytes
	}
	diskCache.Lock()
	diskCache.m[name] = diskSample{bytes: value, at: time.Now()}
	diskCache.Unlock()
	return value
}

// diskDue reports whether the cached value of a container is missing or has expired.
func (c *consoleManager) diskDue(name string) bool {
	diskCache.Lock()
	defer diskCache.Unlock()
	cached, ok := diskCache.m[name]
	return !ok || time.Since(cached.at) >= diskCacheTTL
}
