# Human Action Items

Tasks that require human action outside the codebase.

---

- [ ] **Verify PyPI extras after a release** — publishing is automated (see
  [Release Process](CONTRIBUTING.md#release-process)), but nothing checks that the
  optional dependency groups resolve on a clean install. After a version ships,
  install it from PyPI in a fresh virtualenv:
  ```bash
  pip install dynamo-odata
  pip install dynamo-odata[async]
  pip install dynamo-odata[fastapi]
  ```
