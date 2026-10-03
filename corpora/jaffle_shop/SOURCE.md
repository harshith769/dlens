# Source

- Upstream: https://github.com/dbt-labs/jaffle_shop_duckdb
- Pinned commit: `20cc904370818ceab08cf19f8fd196e9e81def88` (2026-09-28)
- Vendored: 2026-10-03
- Licence: Apache-2.0 (see `LICENSE`)

Files are unmodified copies of `models/`, `seeds/`, `dbt_project.yml`, `profiles.yml`,
`LICENSE`, `README.md` and `.gitignore`. Omitted: `.git`, CI/devcontainer files, images, and
the upstream `pyproject.toml`/`uv.lock` (they would confuse `uv` inside this repo).
Generated `target/`, `logs/` and `*.duckdb` are never committed.
