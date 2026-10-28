package main

import "testing"

func TestCheckPanelURL(t *testing.T) {
	t.Setenv("EPICWING_AGENT_INSECURE", "")
	for raw, ok := range map[string]bool{
		"https://panel.example.com": true,
		"http://127.0.0.1:8010":     true,
		"http://localhost:8010":     true,
		"http://[::1]:8010":         true,
		"http://panel.example.com":  false,
		"ws://panel.example.com":    false,
		"panel.example.com":         false,
		"":                          false,
	} {
		if err := checkPanelURL(raw); (err == nil) != ok {
			t.Errorf("%q: got %v, want ok=%v", raw, err, ok)
		}
	}
	t.Setenv("EPICWING_AGENT_INSECURE", "1")
	if err := checkPanelURL("http://panel.example.com"); err != nil {
		t.Errorf("insecure flag should allow http: %v", err)
	}
}
