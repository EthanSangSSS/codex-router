# Contributing to Codex Router

Thanks for improving Codex Router. Keep contributions bounded, evidence-driven, and compatible with the repository's Native-first safety model.

## Before you start

1. Read `README.md` and `SECURITY.md`.
2. Work from the current `main` branch and keep unrelated changes out of the same pull request.
3. Do not include credentials, private repository content, sensitive local paths, task transcripts, or user data in issues, tests, fixtures, or logs.
4. Do not represent this project as affiliated with or endorsed by OpenAI.

## Development setup

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Required validation

Before opening a pull request, run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

For changes that affect Native installation or managed policy, also exercise the documented install/status/self-test/uninstall lifecycle in an isolated Codex home. Do not claim a real `luna_worker` runtime smoke passed unless that fresh-conversation runtime evidence actually exists.

## Pull requests

A useful pull request should explain:

- the problem and intended behavior;
- the files and surfaces changed;
- validation performed and exact failures or limitations, if any;
- security, permission, compatibility, or migration implications;
- any historical/experimental path affected by the change.

Keep the recommended Native path distinct from historical Hook/K1 compatibility code. Changes that broaden permissions, external writes, process lifetime, or recursive delegation require explicit safety reasoning and tests.

## Security reports

Do not file public issues containing exploit details, credentials, private repository contents, or other sensitive material. Follow `SECURITY.md` for vulnerability reporting.

By contributing, you agree that your contribution is provided under this repository's MIT License.
