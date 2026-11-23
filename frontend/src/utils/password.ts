// Unbiased random index 0..max-1 (rejection sampling, no modulo bias).
function randInt(max: number): number {
  const limit = Math.floor(0x100000000 / max) * max;
  const buf = new Uint32Array(1);
  let x: number;
  do {
    crypto.getRandomValues(buf);
    x = buf[0];
  } while (x >= limit);
  return x % max;
}

export interface PasswordOptions {
  lower?: boolean;
  upper?: boolean;
  digits?: boolean;
  symbols?: boolean;
  avoidAmbiguous?: boolean; // drop 0/O, 1/l/I -> easier to read and type
}

// Generates a strong password. Guarantees at least one character from each
// active set, then shuffles so the order is not predictable.
export function generatePassword(length = 20, opts: PasswordOptions = {}): string {
  const {
    lower = true,
    upper = true,
    digits = true,
    symbols = true,
    avoidAmbiguous = true,
  } = opts;

  const sets: string[] = [];
  if (lower) sets.push(avoidAmbiguous ? "abcdefghijkmnpqrstuvwxyz" : "abcdefghijklmnopqrstuvwxyz");
  if (upper) sets.push(avoidAmbiguous ? "ABCDEFGHJKLMNPQRSTUVWXYZ" : "ABCDEFGHIJKLMNOPQRSTUVWXYZ");
  if (digits) sets.push(avoidAmbiguous ? "23456789" : "0123456789");
  if (symbols) sets.push("!@#$%^&*-_=+?");
  if (sets.length === 0) throw new Error("at least one character set is required");

  const pool = sets.join("");
  const chars: string[] = [];
  for (const s of sets) chars.push(s.charAt(randInt(s.length)));
  while (chars.length < length) chars.push(pool.charAt(randInt(pool.length)));

  // Fisher-Yates shuffle.
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randInt(i + 1);
    const tmp = chars[i]!;
    chars[i] = chars[j]!;
    chars[j] = tmp;
  }
  return chars.join("");
}
