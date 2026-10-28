package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

const testSFTPServerID = "aaaaaaaa-0000-4000-8000-000000000001"

type sftpFixture struct {
	addr    string
	dir     string
	outside string
	signer  ssh.Signer
}

func newSFTPFixture(t *testing.T, write bool) *sftpFixture {
	t.Helper()
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	base := t.TempDir()
	dir := filepath.Join(base, testSFTPServerID)
	must(os.MkdirAll(dir, 0o750))
	must(os.WriteFile(filepath.Join(dir, "hello.txt"), []byte("hi"), 0o640))
	outside := filepath.Join(base, "secret.txt")
	must(os.WriteFile(outside, []byte("secret"), 0o640))
	must(os.Symlink(outside, filepath.Join(dir, "link")))

	_, hostPriv, err := ed25519.GenerateKey(rand.Reader)
	must(err)
	hostSigner, err := ssh.NewSignerFromKey(hostPriv)
	must(err)
	_, userPriv, err := ed25519.GenerateKey(rand.Reader)
	must(err)
	userSigner, err := ssh.NewSignerFromKey(userPriv)
	must(err)
	fp := ssh.FingerprintSHA256(userSigner.PublicKey())

	auth := func(_ context.Context, fingerprint, user string) (sftpGrant, error) {
		if fingerprint != fp || user != "aaaaaaaa" {
			return sftpGrant{}, errors.New("no")
		}
		return sftpGrant{Server: testSFTPServerID, Write: write}, nil
	}
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	must(err)
	srv := newSFTPServer(ctx, hostSigner, auth, func(name string) string { return filepath.Join(base, name) })
	go srv.serve(ln)
	return &sftpFixture{addr: ln.Addr().String(), dir: dir, outside: outside, signer: userSigner}
}

func (f *sftpFixture) client(t *testing.T, user string) (*sftp.Client, error) {
	t.Helper()
	conn, err := ssh.Dial("tcp", f.addr, &ssh.ClientConfig{
		User:            user,
		Auth:            []ssh.AuthMethod{ssh.PublicKeys(f.signer)},
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
		Timeout:         5 * time.Second,
	})
	if err != nil {
		return nil, err
	}
	t.Cleanup(func() { conn.Close() })
	c, err := sftp.NewClient(conn)
	if err != nil {
		return nil, err
	}
	t.Cleanup(func() { c.Close() })
	return c, nil
}

func (f *sftpFixture) mustClient(t *testing.T) *sftp.Client {
	t.Helper()
	c, err := f.client(t, "aaaaaaaa")
	if err != nil {
		t.Fatalf("login failed: %v", err)
	}
	return c
}

func TestSFTPReadAndList(t *testing.T) {
	f := newSFTPFixture(t, false)
	c := f.mustClient(t)

	file, err := c.Open("/hello.txt")
	if err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(file)
	file.Close()
	if err != nil || string(data) != "hi" {
		t.Fatalf("read = %q, %v", data, err)
	}
	infos, err := c.ReadDir("/")
	if err != nil {
		t.Fatal(err)
	}
	names := map[string]bool{}
	for _, i := range infos {
		names[i.Name()] = true
	}
	if !names["hello.txt"] {
		t.Fatalf("listing misses hello.txt: %v", names)
	}
}

func TestSFTPCannotLeaveTheServerFolder(t *testing.T) {
	f := newSFTPFixture(t, true)
	c := f.mustClient(t)

	for _, p := range []string{"/link", "/../secret.txt", "/../../secret.txt"} {
		file, err := c.Open(p)
		if err == nil {
			_, err = io.ReadAll(file)
			file.Close()
		}
		if err == nil {
			t.Fatalf("%s was readable", p)
		}
	}
	if got, _ := os.ReadFile(f.outside); string(got) != "secret" {
		t.Fatal("the outside file changed")
	}
	if err := c.Symlink("/hello.txt", "/l2"); err == nil {
		t.Fatal("creating a symlink must fail")
	}
	if err := c.Rename("/hello.txt", "/../moved.txt"); err != nil {
		// A cleaned path stays inside the folder, so this renames to /moved.txt.
		t.Logf("rename: %v", err)
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(f.dir), "moved.txt")); err == nil {
		t.Fatal("rename left the server folder")
	}
}

func TestSFTPWrite(t *testing.T) {
	f := newSFTPFixture(t, true)
	c := f.mustClient(t)

	up, err := c.Create("/up.txt")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := up.Write([]byte("data")); err != nil {
		t.Fatal(err)
	}
	if err := up.Close(); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(filepath.Join(f.dir, "up.txt")); string(got) != "data" {
		t.Fatalf("uploaded file = %q", got)
	}
	if err := c.Mkdir("/dir"); err != nil {
		t.Fatal(err)
	}
	if err := c.Rename("/up.txt", "/dir/moved.txt"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(f.dir, "dir", "moved.txt")); err != nil {
		t.Fatalf("renamed file is missing: %v", err)
	}
	if err := c.Rename("/dir/moved.txt", "/hello.txt"); err == nil {
		t.Fatal("plain rename over an existing file must fail")
	}
	if err := c.Remove("/dir/moved.txt"); err != nil {
		t.Fatal(err)
	}
	if err := c.RemoveDirectory("/dir"); err != nil {
		t.Fatal(err)
	}
	if err := c.RemoveDirectory("/"); err == nil {
		t.Fatal("removing the root must fail")
	}
	if _, err := os.Stat(f.dir); err != nil {
		t.Fatal("the server folder is gone")
	}
}

func TestSFTPReadOnlyBlocksChanges(t *testing.T) {
	f := newSFTPFixture(t, false)
	c := f.mustClient(t)

	if _, err := c.Create("/x.txt"); err == nil {
		t.Fatal("create must fail")
	}
	if err := c.Remove("/hello.txt"); err == nil {
		t.Fatal("remove must fail")
	}
	if err := c.Mkdir("/d"); err == nil {
		t.Fatal("mkdir must fail")
	}
	if err := c.Rename("/hello.txt", "/h2.txt"); err == nil {
		t.Fatal("rename must fail")
	}
	if _, err := os.Stat(filepath.Join(f.dir, "hello.txt")); err != nil {
		t.Fatal("hello.txt is gone")
	}
	if _, err := os.Stat(filepath.Join(f.dir, "x.txt")); err == nil {
		t.Fatal("x.txt was created")
	}
}

func TestSFTPRejectsUnknownUser(t *testing.T) {
	f := newSFTPFixture(t, true)
	if _, err := f.client(t, "bbbbbbbb"); err == nil {
		t.Fatal("login with a wrong user name must fail")
	}
	if _, err := f.client(t, ""); err == nil {
		t.Fatal("login without a user name must fail")
	}
}

func TestSFTPHostKeyPersists(t *testing.T) {
	file := filepath.Join(t.TempDir(), "host_key")
	first, err := loadOrCreateHostKey(file)
	if err != nil {
		t.Fatal(err)
	}
	second, err := loadOrCreateHostKey(file)
	if err != nil {
		t.Fatal(err)
	}
	if ssh.FingerprintSHA256(first.PublicKey()) != ssh.FingerprintSHA256(second.PublicKey()) {
		t.Fatal("the host key changed")
	}
	if info, _ := os.Stat(file); info.Mode().Perm() != 0o600 {
		t.Fatalf("host key mode = %o", info.Mode().Perm())
	}
}

func TestSFTPAuthBrokerWithoutPanel(t *testing.T) {
	b := &sftpAuthBroker{pending: map[string]chan sftpAuthResult{}}
	if _, err := b.authorize(context.Background(), "SHA256:x", "aaaaaaaa"); err == nil {
		t.Fatal("must fail while the panel is not connected")
	}
}

func TestSFTPAuthBrokerRoundtrip(t *testing.T) {
	b := &sftpAuthBroker{pending: map[string]chan sftpAuthResult{}}
	b.setSend(func(frame map[string]any) {
		go b.resolve(frame["id"].(string), sftpAuthResult{OK: true, Server: testSFTPServerID, Write: true})
	})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	grant, err := b.authorize(ctx, "SHA256:x", "aaaaaaaa")
	if err != nil || grant.Server != testSFTPServerID || !grant.Write {
		t.Fatalf("grant = %+v, %v", grant, err)
	}
	b.setSend(func(frame map[string]any) {
		go b.resolve(frame["id"].(string), sftpAuthResult{OK: false})
	})
	if _, err := b.authorize(ctx, "SHA256:x", "aaaaaaaa"); err == nil {
		t.Fatal("a rejection must be an error")
	}
}
