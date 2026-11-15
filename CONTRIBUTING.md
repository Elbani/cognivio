# Contributing to Cognivio

Bug reports and pull requests are welcome.

## Before you open a pull request

1. Open an issue first for anything larger than a bug fix, so we can agree on the approach
   before you write the code.
2. Run the backend tests. They need a MongoDB on `localhost:27017`:

   ```bash
   cd backend
   pip install -r requirements.txt -r requirements-dev.txt
   pytest
   ```

3. Run the frontend type-check and build:

   ```bash
   cd frontend
   npm ci
   npm run build
   ```

4. Keep `frontend/src/workspace/cognivioRule.ts` in sync with
   `backend/app/core/agent_rules.py` if you touch either.

## Contributor license agreement

The maintainers offer Cognivio under AGPL-3.0 and may offer it under other licenses. To
keep that possible, we ask every contributor to sign a contributor license agreement on
their first pull request. You keep the copyright to your contribution and grant the
maintainers the right to license it under other terms.

## Style

- Python: type hints, small handlers, tests next to the feature in `backend/tests/`.
- TypeScript: the build runs `tsc` in strict mode and must pass.
- No em dashes in code, docs or UI copy.
