# bronco-buddies

![Website diagram](./bronco-buddies.excalidraw.png)

## Development

### Set Up

Set up the environment:

```bash
make setup
```

Create a `.env` (+ `.env.dev` + `.env.local`):

```bash
HF_TOKEN=

DATABASE_URL=
DOMAIN=

GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

EMAIL_SENDER=
SMTP_SERVER=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
```

### Repository Structure

```bash
.
├── .github                 # GitHub Actions.
├── db                      # database.
├── Python-Antivirus        # Python Antivirus.
├── src                     # frontend.
├── .pre-commit-config.yaml # pre-commit config.
├── Makefile                # Makefile.
├── pyproject.toml          # project deps.
├── README.md               # README.
├── uv.lock                 # project deps lock.
```

### Test

Test helpers locally:

```bash
uv run src/helpers.py
```

Test helpers on Modal:

```bash
modal run src/helpers.py
```

Run unit tests:

```bash
uv run pytest -q
```

### App

Migrate db (do before running the app, env=local/dev/main):

```bash
make migrate MSG="your migration message" ENV=main
```

Then, serve the app locally:

```bash
uv run src/app.py
```

Or serve the app on Modal:

```bash
modal serve src/app.py
```

Finally, deploy on main:

```bash
modal deploy src/app.py
```
