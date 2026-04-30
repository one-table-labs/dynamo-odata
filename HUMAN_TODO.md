# Human Action Items

Tasks that require human action outside the codebase.

---

- [ ] **Publish to PyPI** — run `python -m build && twine upload dist/*` (or the equivalent via CI) to publish `dynamo-odata 0.7.0`. Without a PyPI listing, `pip install dynamo-odata` fails. After publishing, verify all three extras install correctly:
  ```bash
  pip install dynamo-odata
  pip install dynamo-odata[async]
  pip install dynamo-odata[fastapi]
  ```

- [ ] **Add GitHub repo topics** — set topics on `one-table-labs/dynamo-odata` via GitHub UI (Settings → Topics):
  `dynamodb`, `odata`, `boto3`, `fastapi`, `aws`, `python`, `single-table-design`, `async`

- [ ] **Generate expand-flow SVG** — `docs/expand-flow.md` contains the Mermaid source for the `$expand` sequence diagram. Generate the rendered SVG and commit it so PyPI and external sites can display the image:
  ```bash
  npm install -g @mermaid-js/mermaid-cli
  mmdc -i docs/expand-flow.md -o docs/expand-flow.svg
  git add docs/expand-flow.svg && git commit -m "docs: add expand-flow SVG"
  ```
