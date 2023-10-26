dev:
  DATASETTE_SECRET=abc123 watchexec --signal SIGKILL --restart --clear -e py,ts,js,html,css,sql -- \
    python3 -m datasette \
      --root \
      -m tests/metadata.yaml \
      --internal internal.db \
      legislators.db

test:
  pytest

format:
  black .
