package main

import (
	"context"
	"errors"
	"testing"
)

func TestStillAllowed(t *testing.T) {
	cases := []struct {
		name string
		got  sftpGrant
		err  error
		want bool
	}{
		{"same rights", sftpGrant{Server: "srv1", Write: true}, nil, true},
		{"rejected", sftpGrant{}, errSFTPRejected, false},
		{"write removed", sftpGrant{Server: "srv1"}, nil, false},
		{"other server", sftpGrant{Server: "srv2", Write: true}, nil, false},
		{"panel offline", sftpGrant{}, errors.New("the panel is not connected"), true},
		{"timeout", sftpGrant{}, context.DeadlineExceeded, true},
	}
	for _, c := range cases {
		s := &sftpServer{
			ctx: context.Background(),
			auth: func(context.Context, string, string) (sftpGrant, error) {
				return c.got, c.err
			},
		}
		if got := s.stillAllowed("fp", "user", "srv1", true); got != c.want {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
		}
	}
}
