package main

import (
	"context"
	"errors"
	"time"
)

// How often an open SFTP connection is checked again.
var sftpRecheckEvery = 60 * time.Second

// sftpConn is the small part of an SSH connection we need here.
type sftpConn interface {
	User() string
	Close() error
}

// stillAllowed asks the panel again. It only returns false when the panel says no
// or the rights changed. If the panel is offline or too slow, the answer is true,
// so a short outage does not kick everybody out.
func (s *sftpServer) stillAllowed(fingerprint, user, server string, write bool) bool {
	ctx, cancel := context.WithTimeout(s.ctx, sftpAuthTimeout)
	defer cancel()
	grant, err := s.auth(ctx, fingerprint, user)
	if errors.Is(err, errSFTPRejected) {
		return false
	}
	if err != nil {
		return true
	}
	return grant.Server == server && grant.Write == write
}

// watchGrant closes the connection when the login is not allowed anymore.
func (s *sftpServer) watchGrant(c sftpConn, ext map[string]string, done <-chan struct{}) {
	fingerprint := ext["fp"]
	server := ext["server"]
	write := ext["write"] == "1"
	tick := time.NewTicker(sftpRecheckEvery)
	defer tick.Stop()
	for {
		select {
		case <-done:
			return
		case <-s.ctx.Done():
			return
		case <-tick.C:
		}
		if !s.stillAllowed(fingerprint, c.User(), server, write) {
			c.Close()
			return
		}
	}
}
