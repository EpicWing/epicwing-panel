import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import ts from "typescript";

// ansi.ts has no imports, so it can be transpiled and loaded directly.
const source = readFileSync(new URL("../src/utils/ansi.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { AnsiBuffer, segmentClass, stripAnsi } = await import(
  "data:text/javascript;base64," + Buffer.from(js).toString("base64")
);

const texts = (buffer) => buffer.lines.map((line) => line.segments.map((s) => s.text).join(""));
const styled = (buffer) => JSON.stringify(buffer.lines.map((line) => line.segments));
const seg = (text, fg = -1, bg = -1, bold = false) => ({ text, fg, bg, bold });

function written(...chunks) {
  const buffer = new AnsiBuffer();
  for (const chunk of chunks) buffer.write(chunk);
  return buffer;
}

test("plain text and line breaks", () => {
  assert.deepEqual(texts(written("a\nb")), ["a", "b"]);
});

test("CRLF is one line break", () => {
  assert.deepEqual(texts(written("a\r\nb\r\n")), ["a", "b", ""]);
});

test("colors and reset", () => {
  const buffer = written("\x1b[31mred\x1b[0m plain");
  assert.deepEqual(buffer.lines[0].segments, [seg("red", 1), seg(" plain")]);
});

test("bold, bright colors and an empty reset", () => {
  assert.deepEqual(written("\x1b[1;92mok").lines[0].segments, [seg("ok", 10, -1, true)]);
  assert.deepEqual(written("\x1b[1;31mA\x1b[mB").lines[0].segments, [seg("A", 1, -1, true), seg("B")]);
});

test("backgrounds, normal and bright", () => {
  assert.deepEqual(written("\x1b[44mX").lines[0].segments, [seg("X", -1, 4)]);
  assert.deepEqual(written("\x1b[101mX\x1b[49mY").lines[0].segments, [seg("X", -1, 9), seg("Y")]);
});

test("style carries over to the next line", () => {
  const buffer = written("\x1b[31mA\nB");
  assert.equal(buffer.lines[1].segments[0].fg, 1);
});

test("a sequence cut in half is completed by the next chunk", () => {
  const buffer = written("\x1b[3", "1mred");
  assert.deepEqual(texts(buffer), ["red"]);
  assert.equal(buffer.lines[0].segments[0].fg, 1);
});

test("a chunk that ends right after ESC", () => {
  const buffer = written("a\x1b", "[32mb");
  assert.deepEqual(buffer.lines[0].segments, [seg("a"), seg("b", 2)]);
});

test("the result does not depend on chunk boundaries", () => {
  const sample =
    "plain \x1b[1;31mred bold\x1b[0m\r\n\x1b[38;5;9mx\x1b[0m 100%\r200%\r\n\x1b]0;title\x07after\x1b(Bz\x1b[2K\x1b[?25h ü 😀\ttab\n";
  const whole = styled(written(sample));
  for (let i = 0; i <= sample.length; i += 1) {
    assert.equal(styled(written(sample.slice(0, i), sample.slice(i))), whole, `split at ${i}`);
  }
  assert.equal(styled(written(...sample)), whole, "character by character");
});

test("cursor movement and erase sequences are dropped", () => {
  assert.deepEqual(texts(written("a\x1b[2Kb\x1b[10;5Hc")), ["abc"]);
});

test("OSC strings end with BEL or ST", () => {
  assert.deepEqual(texts(written("\x1b]0;title\x07x\x1b]0;t\x1b\\y")), ["xy"]);
});

test("an unterminated OSC string does not swallow the console", () => {
  const buffer = written("\x1b]0;" + "a".repeat(2000) + "\nvisible");
  assert.equal(texts(buffer).at(-1), "visible");
});

test("charset and two-character escapes", () => {
  assert.deepEqual(texts(written("\x1b(Bq")), ["q"]);
  assert.deepEqual(texts(written("\x1bcZ")), ["Z"]);
});

test("a broken sequence is dropped, the next one still works", () => {
  const buffer = written("\x1b[3\x1b[32mgreen");
  assert.deepEqual(buffer.lines[0].segments, [seg("green", 2)]);
});

test("ESC before a line break keeps the line break", () => {
  assert.deepEqual(texts(written("a\x1b\nb")), ["a", "b"]);
});

test("256 colors above 15 and truecolor are skipped without garbage", () => {
  const buffer = written("\x1b[38;5;196mA\x1b[38;2;1;2;3mB\x1b[38;5;9mC");
  assert.deepEqual(texts(buffer), ["ABC"]);
  assert.deepEqual(buffer.lines[0].segments, [seg("AB"), seg("C", 9)]);
});

test("colons in SGR parameters are ignored as a whole", () => {
  assert.deepEqual(texts(written("\x1b[38:2::1:2:3mX")), ["X"]);
});

test("a lone carriage return rewrites the line", () => {
  assert.deepEqual(texts(written("10%\r50%\r100%")), ["100%"]);
  assert.deepEqual(texts(written("10%\r", "50%")), ["50%"]);
  assert.deepEqual(texts(written("abc\r\x1b[Kdef")), ["def"]);
});

test("tabs, control characters and C1 controls", () => {
  assert.deepEqual(texts(written("a\tb")), ["a       b"]);
  assert.deepEqual(texts(written("a\x07b\x08c\x00d\u009be")), ["abcde"]);
});

test("markup is kept as text", () => {
  assert.deepEqual(texts(written("<b>x</b> & <script>")), ["<b>x</b> & <script>"]);
});

test("ring buffer keeps the newest lines", () => {
  const buffer = new AnsiBuffer(100);
  for (let i = 0; i < 1000; i += 1) buffer.write(`line ${i}\n`);
  assert.ok(buffer.lines.length >= 100 && buffer.lines.length <= 110, `length ${buffer.lines.length}`);
  assert.equal(texts(buffer).at(-2), "line 999");
  const ids = buffer.lines.map((line) => line.id);
  assert.deepEqual(ids, [...ids].sort((a, b) => a - b));
});

test("long lines wrap softly and lose nothing", () => {
  const buffer = new AnsiBuffer(100, 10);
  buffer.write("x".repeat(25));
  assert.deepEqual(texts(buffer), ["x".repeat(10), "x".repeat(10), "x".repeat(5)]);
});

test("soft wrap does not split a surrogate pair", () => {
  const buffer = new AnsiBuffer(100, 5);
  buffer.write("abcd😀ef");
  assert.equal(texts(buffer).join(""), "abcd😀ef");
  for (const line of texts(buffer)) assert.ok(!/[\ud800-\udbff]$/.test(line) && !/^[\udc00-\udfff]/.test(line));
});

test("rev changes when a line changes", () => {
  const buffer = new AnsiBuffer();
  const before = buffer.lines[0].rev;
  buffer.write("a");
  assert.ok(buffer.lines[0].rev > before);
});

test("clear starts over", () => {
  const buffer = written("\x1b[31mtext\nmore");
  buffer.clear();
  buffer.write("x");
  assert.deepEqual(buffer.lines.map((l) => l.segments), [[seg("x")]]);
});

test("segmentClass", () => {
  assert.equal(segmentClass(seg("x", 1)), "ansi-fg-1");
  assert.equal(segmentClass(seg("x", -1, 4, true)), "ansi-bg-4 ansi-bold");
  assert.equal(segmentClass(seg("x")), "");
});

test("stripAnsi still removes complete sequences", () => {
  assert.equal(stripAnsi("\x1b[31mx\x1b[0m"), "x");
});

test("large colored output is parsed quickly", () => {
  const buffer = new AnsiBuffer();
  const line = "\x1b[32m[INFO]\x1b[0m something happened \x1b[1;33mwarning\x1b[0m 12345\r\n";
  const start = performance.now();
  for (let i = 0; i < 100000; i += 1) buffer.write(line);
  const ms = performance.now() - start;
  console.log(`100000 lines in ${ms.toFixed(0)} ms`);
  assert.ok(buffer.lines.length <= 3300);
  assert.ok(ms < 5000);
});
