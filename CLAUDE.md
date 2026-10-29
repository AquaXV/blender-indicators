# Feature workflow

- Every new feature is built on its own feature branch, based on `main`.
- Keep working on the feature branch until the user explicitly says the feature is completed. Only then merge it back into `main`.

# Commits

- After every pass, before handing back to the user, commit the work.
- Commit messages must not contain `Co-Authored-By` or any other co-author tags.

# Releases

`./release.sh [major|minor|patch]` bumps the version in `blender_manifest.toml`, builds `dist/<id>-X.Y.Z.zip`, commits, tags `vX.Y.Z` and pushes the branch and tag.
