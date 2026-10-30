<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="app/static/logo-dark.svg">
    <img src="app/static/logo.svg" alt="Curlbook" width="480">
  </picture>
</p>

A small, self-hosted, HTML-based Postman alternative. Save curl commands with
their payloads into a local JSON file, organise them into collections, and chain
requests together using global variables extracted from responses.

## Run

```bash
docker compose up -d --build
open http://localhost:8787
```

Use a different host port with `CURLBOOK_PORT=9000 docker compose up -d`.

All data is stored in `./data/store.json` (bind-mounted to `/data`). Back it up,
commit it, or hand-edit it while the container is stopped. The container entrypoint
fixes ownership of `./data` automatically and then runs as an unprivileged user.

Without Docker:

```bash
pip install -r requirements.txt
cd app && CURLBOOK_DATA_DIR=../data python server.py
```

## Features

- **Collections**: group requests; create, rename, delete, duplicate, move (via the "in" dropdown), search.
- **Tags**: add tags to any request (type and press Enter, comma or Tab; Backspace removes the last one;
  existing tags are suggested). Tags are lowercase and each tag gets its own unique colour, shown on the
  request in the sidebar. Click a tag's colour dot in the editor to recolour it (colours must stay unique).
  Tags can also be set when importing a curl.
- **Search**: words match request name, URL, method, collection and tags; `tag:name` (or `#name`) filters
  by exact tag; multiple terms must all match (e.g. `tag:auth tag:prod login`). Clicking a tag chip in the
  sidebar toggles it as a filter.
- **Manual editor**: method dropdown, URL, headers (toggle on/off), raw body with *Format JSON*,
  options: *Insecure* (`-k`), *Follow redirects* (`-L`), *Timeout* (`-m`).
- **Raw curl tab**: two-way sync. Edit or paste a curl and click *Apply to form*;
  form edits regenerate the curl. *Copy with variables resolved* gives you a ready-to-run command.
- **Paste curl into the URL bar**: it's parsed into the form automatically.
- **Import curl**: paste a command, pick a collection, and it's parsed + saved.
  Supports `-X -H -d --data --data-raw --data-binary --data-urlencode --json -k -L -u -b -A -e
  -G -I -m --url --compressed` plus combined short flags (`-sSLk`), `$'...'` quoting and `\` line continuations.
  Unsupported options (e.g. `-F`, `@file` data) are reported as warnings.
- **Global variables**: use `{{name}}` in URL, headers, or body. Substituted server-side right before sending.
  Chips under the URL bar show which variables are defined/undefined.
  Built-ins: `{{$uuid}}`, `{{$timestamp}}`, `{{$timestampMs}}`, `{{$randomInt}}`.
- **Extraction rules** (per request, *Extract* tab): after every send, values are pulled from the response
  into globals and persisted.
  - `body` + path like `data.items[0].id`, `items[-1].name`, `data["weird.key"]`, `items.length`
  - `header` + header name (case-insensitive), e.g. `Set-Cookie`
  - `status` - the HTTP status code
- **Click-to-extract**: click any key/value in the JSON response (or a response header name) to fill the
  *Save to global* bar; preview, save as a global directly, or add it as a permanent rule.
- **Response view**: status, time, size, pretty JSON, headers, and the exact curl that was sent
  (after substitution).
- **Light / dark theme**: light by default; toggle dark mode with the moon/sun button in the top bar
  (remembered per browser).
- **Version history** (git): every save is committed — see [History](#history).

Keyboard: `Ctrl/Cmd+Enter` send, `Ctrl/Cmd+S` save, `Esc` close dialogs.

## History

Saved requests are versioned in a git repository at `./data/history` (one file per request,
`requests/<id>.json`). Every create, save, move, duplicate, delete, import and collection rename/delete
makes a commit with a readable message such as `Update "Login": url, body`; saving without changes makes none.

- **History tab** on each request: list of versions; pick one to see *what that version changed* or
  *compare it with the current* request as a diff of the curl (plus name, tags, extract rules and disabled
  headers). *Restore this version* loads it into the editor as unsaved changes — save to make it current,
  so nothing is ever overwritten. *Copy curl* copies that version's command.
- **Recently deleted** (bottom of the sidebar): bring back deleted requests, with their history intact.
- Globals are **not** tracked (they hold tokens and change on every send that extracts values).
- It's a normal repo: `git -C data/history log --stat` works from your terminal.
- On startup, hand-edits to `store.json` are recorded as `Sync external changes`.
- History is best-effort: if git is unavailable or fails, saving still works. Disable it with `CURLBOOK_HISTORY=0`.
  Running without Docker requires `git` on your `PATH`.

## Calling services on your host

Requests run from inside the container, where `localhost` would be the container itself (and port
8080 is curlbook's own server). So the Docker image sets `CURLBOOK_LOCALHOST_ALIAS=host.docker.internal`:
URLs pointing at `localhost`, `127.0.0.1`, `::1`, `0.0.0.0` or `*.localhost` are sent to your machine
instead, with the original `Host` header kept. A copied curl therefore behaves the same in your terminal
and in the UI. Set `CURLBOOK_LOCALHOST_ALIAS=` (empty) to disable this.
Tip: keep the base URL in a global such as `{{baseUrl}}` so switching hosts is a one-line change.

## Configuration

| Env var                    | Default (Docker)       | Description                                    |
|----------------------------|------------------------|------------------------------------------------|
| `CURLBOOK_DATA_DIR`        | `/data`                | Directory holding `store.json`                 |
| `CURLBOOK_MAX_BODY_BYTES`  | `10485760`             | Max response body size kept                    |
| `CURLBOOK_LOCALHOST_ALIAS` | `host.docker.internal` | Host that loopback URLs are redirected to      |
| `CURLBOOK_HISTORY`         | `1`                    | Set to `0` to disable git version history      |
| `CURLBOOK_HISTORY_DIR`     | `$CURLBOOK_DATA_DIR/history` | Location of the history git repo         |
| `PORT`                     | `8080`                 | Listen port inside the container               |
| `CURLBOOK_PORT`            | `8787`                 | Host port published by compose                 |

## Logo

The logos in `app/static/` are generated by `tools/gen_logo.py`: "CurlBook" in cursive, drawn like
blue ballpoint ink with a red offset shadow line, on two light ruled lines (baseline and x-height) that
the capitals and ascenders overshoot.

| File | Use |
|---|---|
| `logo.svg` / `logo-dark.svg` | large logo (welcome screen, README) |
| `logo-wordmark.svg` / `logo-wordmark-dark.svg` | top bar; swapped automatically with the theme |
| `logo-icon.svg` | favicon - cursive "C" on a ruled paper square |

The text is shaped with HarfBuzz from the bundled [Sacramento](tools/fonts/) font (SIL Open Font
License, see `tools/fonts/OFL.txt`) and converted to plain SVG paths, so no font is needed at runtime.
To tweak colours, offsets or line positions, edit the top of the script and run:

```bash
pip install -r tools/requirements.txt
python3 tools/gen_logo.py
```

## Security note

There is no authentication. Compose publishes the port on `127.0.0.1` only - keep it that way
unless you put it behind something that authenticates. Since the server makes arbitrary
HTTP requests on your behalf, don't expose it publicly.
