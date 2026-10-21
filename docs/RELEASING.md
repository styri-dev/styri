# Releasing Styri Core

Releases are tags. CI does the building, testing and publishing; this is
what a person does around it. Use the new version in place of `vX.Y.Z`.

## Before tagging

- [ ] CI is green on `main` (every e2e combination, both quickstarts).
- [ ] The version is bumped everywhere it lives:
      `bridge/setup.py`, `bridge/styri_bridge/__init__.py`,
      `bridge/package.xml`, `ui/package.json` (then
      `npm --prefix ui install --package-lock-only`).
- [ ] The quickstart and examples name the new tag: `README.md`, `docs/`
      and the `Dockerfile` comment (`git grep styri-core:v`).
- [ ] Notes that say a feature is "coming in the next release" are gone.

## Tag

```bash
git tag -a vX.Y.Z -m "Styri Core vX.Y.Z" && git push origin vX.Y.Z
```

The tag's CI run reruns everything, publishes
`ghcr.io/styri-dev/styri-core:vX.Y.Z` for linux/amd64 and linux/arm64, runs
the quickstart with that exact tag on clean x86 and Arm runners (anonymous
pull), and only then creates the GitHub release.

## After the release run is green

- [ ] The image is public and multi-arch. With no registry login:
      `docker buildx imagetools inspect ghcr.io/styri-dev/styri-core:vX.Y.Z`
      lists linux/amd64 and linux/arm64. (The two "unknown/unknown" entries
      are build attestations.)
- [ ] The release page exists: `https://github.com/styri-dev/styri/releases/tag/vX.Y.Z`.
- [ ] **Re-run `docs/media/make-hero.sh`** so the README hero GIF shows the new
      tag (it records the latest `v*` tag; the image must already be
      published). Commit `docs/media/hero.gif`.
- [ ] In styri-pro: pin `core/` to the tag
      (`git -C core fetch --tags && git -C core checkout vX.Y.Z && git add core`)
      and update the quickstart on the website (`site/index.html`) and in
      `docs/TWO-MACHINE-TEST.md`.
