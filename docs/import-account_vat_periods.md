# account_vat_periods: merge from 18.0-dev-veroapi into 18.0-dev

## Why

`18.0-dev` already shipped a base `account_vat_periods` module. `18.0-dev-veroapi`
(same repo, `OCA-Finland/dev-test`) had a newer, purely additive version of the
same module with the Finnish Vero API filing feature layered on top (17 files
changed vs. the `18.0-dev` copy, all additions: `README_VERO_API.md`,
`vero_payload.py`, `models/vero_backend.py`, `models/vero_report.py`,
`models/vero_vat_period.py`, `tests/test_vero_api.py`, etc. — see the diff in the
commit history below).

Having the same module available with diverging content on two different
branches is a source of ambiguity for anything that builds or deploys from this
repo — whichever branch happens to be used can silently ship a different version
of `account_vat_periods`. This merge consolidates both versions into `18.0-dev` so
there is only one, up-to-date copy of the module going forward.

## What was done

Repo: https://github.com/OCA-Finland/dev-test
Merge direction: `18.0-dev-veroapi` → `18.0-dev` (same repository, branch to branch)
Path: `account_vat_periods`

### Method: `git subtree split` + `git subtree add --squash`

Chosen over a plain `git checkout <branch> -- <path>` copy because `account_vat_periods`
on `18.0-dev-veroapi` is still under active development and this keeps a
re-syncable link to its upstream history instead of a one-off snapshot.

```bash
# In a clone of dev-test, branch 18.0-dev checked out:
git fetch origin 18.0-dev-veroapi:refs/remotes/origin/18.0-dev-veroapi

# Isolate the module's history from the veroapi branch
git subtree split --prefix=account_vat_periods -b split-account-vat-periods \
  origin/18.0-dev-veroapi

# 18.0-dev already had an older account_vat_periods; subtree add requires the
# destination path not to exist, so remove the old version first
git rm -r account_vat_periods
git commit -m "Remove outdated account_vat_periods prior to subtree import from 18.0-dev-veroapi"

# Merge in the new version, squashed into a single commit
git subtree add --prefix=account_vat_periods split-account-vat-periods --squash
```

The source branch had `__pycache__/*.pyc` files committed under
`account_vat_periods/` (upstream hygiene issue — this repo currently has no
`.gitignore` at all, which is a separate pre-existing gap, not addressed here).
Those `.pyc` files were stripped from the merge commit with
`git rm -r --cached` + `git commit --amend` before finalizing.

Resulting commits on `18.0-dev` (oldest to newest):
1. `Remove outdated account_vat_periods prior to subtree import from 18.0-dev-veroapi`
2. `Merge commit '...' as 'account_vat_periods'` (squashed import, pycache-free)
3. This documentation commit

## Future updates

To pull a newer version of `account_vat_periods` from `18.0-dev-veroapi` later:

```bash
git fetch origin 18.0-dev-veroapi:refs/remotes/origin/18.0-dev-veroapi
git subtree split --prefix=account_vat_periods -b split-account-vat-periods-update \
  origin/18.0-dev-veroapi
git subtree merge --prefix=account_vat_periods split-account-vat-periods-update \
  --squash
```

(`git subtree pull` also works and does fetch+merge in one step, but doing the
split explicitly first makes it easy to review the isolated diff before merging.)

## Follow-up

- Confirm no deployment or build process for this module still pulls from
  `18.0-dev-veroapi` separately — if one does, point it at `18.0-dev` instead, to
  avoid two divergent copies of `account_vat_periods` ending up on the same
  target.
- Run the Odoo module update for `account_vat_periods` wherever this branch is
  deployed (`-u account_vat_periods`, or Apps → Update Apps List → Upgrade) so the
  database picks up the merged code.
