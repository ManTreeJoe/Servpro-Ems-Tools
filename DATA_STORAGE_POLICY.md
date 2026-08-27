# Linguar Hub data storage policy

Linguar Hub databases are text-first indexes, not file stores.

## Store in SQLite and Supabase

- Human-readable names, notes, comments, statuses, dates, and identifiers.
- Small structured values such as checklist state, labels, and revision details.
- File names, local folder paths, CompanyCam document IDs, and web links.
- Search and synchronization metadata needed to connect the same job across systems.

## Never store in SQLite or Supabase

- Photos, videos, PDFs, Word files, spreadsheets, or ZIP files.
- Base64 or other text encodings of those files.
- Full downloaded responses when a small shaped record is enough.

Files remain in the job folder, CompanyCam, or the system that owns them. The
database stores only enough text to find, identify, search, and track the file.

## Structured text

JSON is allowed only for small structures whose shape varies, including labels,
checklist state, event details, and revision snapshots. Frequently searched job
facts belong in named text/date columns instead of a JSON field.

Any future document/signature table must store metadata only: document ID, job
ID, file name, path or URL, status, signer names/emails, and timestamps.
