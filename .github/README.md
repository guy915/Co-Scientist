# GitHub maintenance

`labels.yml` is the label catalog. Synchronize it when preparing the public
repository; existing labels need not be deleted. Issue forms use `type: bug`,
`type: feature`, and `needs triage`, so those labels must exist at launch.
Enable Discussions for the question/support link in the issue chooser.
`CODEOWNERS` routes launch/community configuration to the current maintainer.
Source and campaign paths need additional reviewers before mandatory ownership;
add actual collaborators when they receive repository access.

## CI

`ci.yml` uses the PR diff for presubmit and the merge group's base/head diff
for queue checks. Markdown and `docs/` changes alone exclude typecheck/test
targets in those events. Lint remains selected where its original filter
matches. Main pushes, manual runs, and nightly calls select every target. Their CI
concurrency groups are unique per run, so GitHub cannot replace a pending
postsubmit when another commit arrives. PRs still supersede older runs.
The Chromium cache is tied to OS, architecture, and the e2e lock; installation
still checks system dependencies. Mypy restores incremental data for the same
Python/dependency/config identity and validates source changes as usual.

Ruff and MCP share a runner; mypy/import contracts and root-config smoke share
another. The validation commands, working directories, and environments are
preserved. Compatibility checks retain names required by the existing ruleset;
`Required checks` rejects any selected failure or cancellation. CodeQL runs
Python and JavaScript/TypeScript analysis separately from the hermetic test
pipeline, using GitHub's scanning infrastructure.

## Main ruleset at launch

GitHub merge queues require organization ownership. This public repository is
currently owned by a personal account; the owner must transfer it to an
organization or defer queue activation. The queue-enabled import file is for
launch once the repository is eligible. See [GitHub availability](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/merging-a-pull-request-with-a-merge-queue).

Import `rulesets/main.json` through GitHub's ruleset import UI. It requires a
PR and `Required checks`, forbids deletion/force pushes, resolves review
threads, allows squash only, and enables the merge queue. It has no bypass
actors and no up-to-date rule. Approval count is zero for the current solo
maintainer; CODEOWNERS routes review without requiring self-approval.

Replace or disable the overlapping `Default` ruleset (17522178): leaving it
active retains its ten legacy required contexts and strict/up-to-date rule.
Enable squash merges and disable merge/rebase methods in repository settings
as well. Set the queue's merge method to squash and require `Required checks`.
These are owner actions; committing these files does not change settings.

Queue validation uses a throwaway branch to replay base/head payloads through
the pinned production paths-filter action and target selector. An actual
`merge_group` event is emitted only after the owner enables the queue; its
first queued merge is the final platform integration check.

Before launch, also enable private vulnerability reporting and confirm CodeQL
results appear under Security. The campaign's complete owner list and handoffs
are recorded on [board #332](https://github.com/guy915/Co-Scientist/issues/332).
