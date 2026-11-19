# 1.8.48 updater recovery and corrections

## Shipped artifact evidence (2026-11-19)

The GitHub release API for `ManTreeJoe/linguar-hub-releases`, tag `v1.8.48`, reports
`Linguar-Hub-Setup-1.8.48.exe`, 63,407,024 bytes, SHA256
`5f7c251d891260693885ef4b3f1ba8bb852e5e9ebc27f85784c2b17f267a6084`.
The preserved local installer has exactly that size and SHA256. The live GitHub
`main/version.txt` identifies 1.8.48 and describes the private-feed transition.
The prepared transition report's unbuilt claim is not evidence of what shipped.

Extracted the bundled executable without running setup or the application, using
innoextract 1.12-dev/e561d8c (6.7.0-compatible Windows build). Archive SHA256:
`79b69b9b1fcd98f42ccd4b245efdf6a03bcfb674ba6af482f5a46891c9ed4d14`.
The older official 1.9 extractor could not read this installer format.
PyInstaller's archive reader extracted code objects; no application module was imported.
Compared those objects to Python 3.12 compilation of the original recovered PR
source, before the review corrections. Comparison includes recursive bytecode,
constants, names, arguments, locals, closure variables, flags and exception tables;
excludes source paths and line-location tables. This proves equivalent compiled
structure for the named code, not original source formatting/comments or the whole app.

```text
PYZ update_check
shipped normalized SHA256: c6f1e29cac49f71969a78b8bb8153d26e2b2815a2031a344702e9fb7a384f957
PR-original normalized SHA256: c6f1e29cac49f71969a78b8bb8153d26e2b2815a2031a344702e9fb7a384f957
diff: EMPTY
PYZ home_web.install_update
shipped normalized SHA256: 639774c1a9661736e7b43527c5bea69887b5747c76eeffde8254eb33dde42694
PR-original normalized SHA256: 639774c1a9661736e7b43527c5bea69887b5747c76eeffde8254eb33dde42694
diff: EMPTY
entry home_web.install_update
shipped normalized SHA256: 639774c1a9661736e7b43527c5bea69887b5747c76eeffde8254eb33dde42694
PR-original normalized SHA256: 639774c1a9661736e7b43527c5bea69887b5747c76eeffde8254eb33dde42694
diff: EMPTY
```

## Review corrections beyond shipped behavior

- Main checks both valid feeds and selects the highest version; ties prefer private.
- Trial remains GitHub-only. An empty legacy installer falls back to its release page.
- Installer launch uses only the validated feed result, never a caller-supplied URL.
- Automatically downloaded installers are SHA256 checked when the feed supplies a
  checksum; mismatch prevents launch. Legacy feeds without a checksum remain supported.
- Access-protected private downloads remain browser-only. The app neither executes
  those downloads nor claims to verify browser-managed bytes. Private checksum format
  is validated, but employee-side download verification remains a rollout requirement.

Older clients still require their original GitHub feed. This PR does not change
servers, routes, manifests or releases. The checksum is integrity metadata, not
independent publisher authentication; signing and rollout review remain separate.

Focused tests use fake HTTP responses and an extracted method with fake browser and
installer launch functions. No application launcher or installer was run.
