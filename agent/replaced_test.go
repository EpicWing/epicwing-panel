package main

import (
	"errors"
	"fmt"
	"testing"

	"github.com/coder/websocket"
)

func TestIsReplaced(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"newer connection", websocket.CloseError{Code: statusReplaced, Reason: replacedReason}, true},
		{"wrapped", fmt.Errorf("reading from the panel: %w", websocket.CloseError{Code: statusReplaced, Reason: replacedReason}), true},
		{"panel restart without reason", websocket.CloseError{Code: statusReplaced}, false},
		{"other reason", websocket.CloseError{Code: statusReplaced, Reason: "restart"}, false},
		{"other code", websocket.CloseError{Code: websocket.StatusPolicyViolation, Reason: replacedReason}, false},
		{"plain error", errors.New("boom"), false},
		{"nil", nil, false},
	}
	for _, c := range cases {
		if got := isReplaced(c.err); got != c.want {
			t.Errorf("%s: isReplaced = %v, want %v", c.name, got, c.want)
		}
	}
}
