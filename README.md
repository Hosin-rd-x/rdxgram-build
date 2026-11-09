# rdxgram-build

GitHub Actions build for the **RDX Gram** glass navigation bar patch — the
definitive InstaPro 15.90 build (bundle 0.6.0, Morphe `--bytecode-mode FULL`).

Previously this was built on Hossein's AWS server; the server's disk was 86%
full, so the build moved here. The built APKs are published on his own
server at `shop.hosinrdx.ir` — GitHub is only the build machine.

## What it builds

One patch, applied to untouched stock InstaPro 15.90
(`com.instapro.android`, 439.0.0.38.89):

- flat floating bar in the bottom navigation: strokeWidth 80.0f px (~29dp),
  30dp side insets, Butt caps, color 70% `#CCCCCC`
  (`0xB3CCCCCC00000000`), 48dp bar height unchanged.

Two outputs:

| file | signing | installs |
| --- | --- | --- |
| `InstaPro-15.90-glass-final.apk` | Morphe default key | clean install only (uninstall first) |
| `InstaPro-15.90-glass-final-testkey.apk` | AOSP testkey (same cert as stock) | **over the current stock install, no uninstall** |

Reference build (server, 2026-11-09), both 183,192,752 bytes:

- Morphe-signed SHA-256: `f6d693cd47f4945c0170a44fe41d96dde4fd9a051b77e7f0db15367dde9f18b2`
- Testkey twin SHA-256: `246217a9eca8b5e0fb61f8c99d09e087bb7664c8316864bdf914cb5b80e9c538`

## How to run

Actions → **Build InstaPro glass-final** → Run workflow. The run takes a
few minutes and uploads both APKs (+ the Morphe patch report and log) as
the `instapro-glass-final` artifact.

## What is (and is not) in this repo

- `patches-0.6.0.mpp` — the prebuilt Morphe patch bundle. Prebuilt on the
  server because the Morphe Gradle plugin needs GitHub Packages auth for
  the MorpheApp registry, which is not available inside Actions.
  SHA-256: `e70af2047dfcbcd23c697e40ac63799cfcf52bb7d45ad4e39558a4bd13216184`
- `patches-src/` — the patch source (`GlassNavPatch.kt.final`,
  `Constants.kt`) for reference. The definitive source is generated from
  the glass3 source by `make_final.py` (kept with the project notes).
- `.github/workflows/build.yml` — the build.

Never in this repo, ever:

- the stock InstaPro APK (180 MB, over GitHub's 100 MB file limit, and a
  modded proprietary binary) — the workflow downloads it from
  `https://shop.hosinrdx.ir/InstaPro-15.90.apk` and verifies its SHA-256
  (`06f77692583257db911294fdac46682418c9331acbbb2a94ff7c5ed1b919edca`).
- the testkey keystore or its password — they live only as GitHub Actions
  secrets (`TESTKEY_P12_B64`, `TESTKEY_PASSWORD`) and on Hossein's server.
- any other secret, token, or password.

## Verification profile of a correct build

- `zipalign -c -v 4` passes on both APKs
- 18 dex files, no `classes21.dex`, no `META-INF` on the Morphe build
- 183,253 classes, zero missing vs stock; `Uq1` and `lpR` exactly once each
- manifest byte-identical to stock
- smali diff vs stock limited to the two patched classes (`Uq1` +1
  instruction, `lpR` case-17 8→24 instruction replacement)

Note: the Morphe-signed APK's SHA may differ from the server build — Morphe
signs with a keystore it generates on first run, and the runner gets a fresh
one (different cert than the server's). Only the signature block differs.
The testkey twin is re-signed with the same testkey, so it should be
byte-identical to the server build if the Morphe rebuild is deterministic.
