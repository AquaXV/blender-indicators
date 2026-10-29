#!/usr/bin/env bash
# Bump the extension version, build the zip, commit, tag and push.
#
# Usage: ./release.sh [major|minor|patch]   (default: patch)
# Set BLENDER to choose the Blender binary used for the build.
set -euo pipefail

cd "$(dirname "$0")"

PART=${1:-patch}
BLENDER=${BLENDER:-blender}
MANIFEST=blender_manifest.toml

case $PART in
  major | minor | patch) ;;
  *) echo "usage: $0 [major|minor|patch]" >&2; exit 1 ;;
esac

if [[ -n $(git status --porcelain) ]]; then
  echo "working tree is not clean" >&2
  exit 1
fi

ID=$(sed -n 's/^id = "\(.*\)"/\1/p' "$MANIFEST")
OLD=$(sed -n 's/^version = "\(.*\)"/\1/p' "$MANIFEST")
IFS=. read -r MAJOR MINOR PATCH <<<"$OLD"
case $PART in
  major) NEW="$((MAJOR + 1)).0.0" ;;
  minor) NEW="$MAJOR.$((MINOR + 1)).0" ;;
  patch) NEW="$MAJOR.$MINOR.$((PATCH + 1))" ;;
esac
TAG="v$NEW"

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "tag $TAG already exists" >&2
  exit 1
fi

sed -i "s/^version = \"$OLD\"/version = \"$NEW\"/" "$MANIFEST"
trap 'git checkout -- "$MANIFEST"' ERR

# Build from tracked files only, so untracked or ignored files never end up in the zip.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
git ls-files -z | xargs -0 cp --parents -t "$STAGE"
cp "$MANIFEST" "$STAGE/$MANIFEST"
mkdir -p dist
ZIP="$PWD/dist/$ID-$NEW.zip"
"$BLENDER" --factory-startup --command extension build --source-dir "$STAGE" --output-filepath "$ZIP"

git commit -q -m "Release $TAG" -- "$MANIFEST"
trap - ERR
git tag -a "$TAG" -m "Release $TAG"
git push origin HEAD "refs/tags/$TAG"

echo "Released $TAG: $ZIP"
