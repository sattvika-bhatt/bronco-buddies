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

### Useful Tips

Migrate db (do before running the app, env=local/dev/main):

```bash
make migrate MSG="your migration message" ENV=dev
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

### App

Serve the app locally:

```bash
uv run src/app.py
```

Serve the app on Modal:

```bash
modal serve src/app.py
```

Deploy on dev:

```bash
modal deploy src/app.py
```

Deploy on main:

```bash
modal deploy --env=main src/app.py
```
