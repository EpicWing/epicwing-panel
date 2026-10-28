#!/usr/bin/env bash
# Syncs install scripts from backend/fixtures/eggs/*.sh into the eggs table.
# Every fixture names its egg with a "# egg-name: <name>" header line.
# Dry run by default; pass --apply to write.
set -euo pipefail
cd "$(dirname "$0")/.."

url="${DATABASE_URL:-$(grep -h '^DATABASE_URL=' backend/.env | head -1 | cut -d= -f2-)}"
url="${url/postgresql+psycopg/postgresql}"
apply=0
[[ "${1:-}" == "--apply" ]] && apply=1

for file in backend/fixtures/eggs/*.sh; do
    name="$(sed -n 's/^# egg-name: //p' "$file" | head -n 1)"
    if [[ -z "$name" ]]; then
        echo "skip   $file (missing egg-name header)" >&2
        continue
    fi
    bash -n "$file"
    body="$(cat "$file")"

    state="$(psql "$url" -At -v name="$name" -v body="$body" <<'SQL'
SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM eggs WHERE name = :'name') THEN 'missing'
    WHEN EXISTS (SELECT 1 FROM eggs WHERE name = :'name'
                 AND rtrim(install_script, E'\n') = :'body') THEN 'current'
    ELSE 'outdated'
END;
SQL
)"
    echo "$state  $name  ($file)"

    if [[ "$state" == "outdated" && $apply -eq 1 ]]; then
        psql "$url" -v ON_ERROR_STOP=1 -v name="$name" -v body="$body" <<'SQL'
UPDATE eggs SET install_script = :'body' || E'\n', updated_at = now()
WHERE name = :'name';
SQL
    fi
done
