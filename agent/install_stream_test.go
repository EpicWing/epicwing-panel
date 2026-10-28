package main

import (
	"strings"
	"testing"
	"unicode/utf8"
)

func collect() (*chunkWriter, *[]string) {
	var got []string
	return &chunkWriter{emit: func(s string) { got = append(got, s) }}, &got
}

func TestChunkWriterSplitsOnLines(t *testing.T) {
	w, got := collect()
	_, _ = w.Write([]byte("one\ntw"))
	_, _ = w.Write([]byte("o\nthree"))
	w.Flush()
	want := []string{"one\n", "two\n", "three"}
	if strings.Join(*got, "|") != strings.Join(want, "|") {
		t.Fatalf("got %q, want %q", *got, want)
	}
}

func TestChunkWriterLimitsChunkSize(t *testing.T) {
	w, got := collect()
	_, _ = w.Write([]byte(strings.Repeat("x", 5000)))
	w.Flush()
	total := 0
	for _, s := range *got {
		if len(s) > consoleChunkBytes {
			t.Fatalf("chunk of %d bytes", len(s))
		}
		total += len(s)
	}
	if total != 5000 {
		t.Fatalf("lost bytes: %d", total)
	}
}

func TestChunkWriterKeepsUTF8Intact(t *testing.T) {
	w, got := collect()
	input := strings.Repeat("a", consoleChunkBytes-1) + "é" + "end"
	_, _ = w.Write([]byte(input))
	w.Flush()
	for _, s := range *got {
		if !utf8.ValidString(s) {
			t.Fatalf("invalid UTF-8 chunk %q", s)
		}
	}
	if strings.Join(*got, "") != input {
		t.Fatal("output changed")
	}
}
