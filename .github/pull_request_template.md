## Change

Describe the problem and the resulting behavior.

## Validation

List the relevant checks and their results. For launch-wide changes, run
`make check` and `make docker-build`. State anything that remains unverified.

- [ ] `make lint` (exit status: )
- [ ] `make typecheck` (exit status: )
- [ ] `make arch` (exit status: )
- [ ] `.venv/bin/python -m pytest evaluations/tests/ -q` (exit status: )
- [ ] `make test-all` (exit status: )
- [ ] `make e2e` (exit status: )

Workflow changes: link the latest-commit run and show that selected commands ran
and excluded targets were correctly skipped.

Model-affecting changes: benchmark scores before and after (see the quality
benchmark in evaluations/README.md).

## Release notes

Note configuration changes, migrations, or operational steps when applicable.
