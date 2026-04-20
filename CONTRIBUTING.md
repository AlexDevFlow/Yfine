# Contributing

Bug reports, translations, and code are all welcome.

## Setup

```bash
git clone https://github.com/<your-fork>/Yfine.git
cd Yfine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Tests

```bash
pip install pytest
pytest
```

New logic in `services/` and `routers/` should come with tests.

## Code style

- Python 3.11+
- Routers parse input, call a service, return a response. No business logic in routers.
- Services take a `Session` as first argument. They don't call `get_session` themselves.
- API requests and responses use the shapes in `schemas/`. Don't return raw SQLModel instances.
- Every UI string goes through `_()`. No hardcoded English in templates.
- Amounts stay in their source currency. No silent conversion.

## Translations

Locale files are in `locales/{code}.json`. To add a new language, copy `en.json` and translate. New locales are welcome.

## Pull requests

Before opening one:

- Tests pass (`pytest`)
- No hardcoded UI strings
- New endpoints under `/api`
- Alembic migration if the schema changed

Commit messages: short, imperative, lowercase. `fix recurring item applied twice when clock skew` is a fine example.

## Security issues

Don't open a public issue. See [SECURITY.md](SECURITY.md).
