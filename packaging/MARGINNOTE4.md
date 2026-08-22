# MarginNote 4 production setup

## Security model

- DeepTutor is a read-only mirror; MarginNote 4 remains the source of truth.
- Each library allows one active device. Revoke it in DeepTutor before pairing a new installation.
- Pairing codes are one-time values, expire in ten minutes, and only their SHA-256 hashes are stored.
- Device tokens are 32-byte random values and are returned once. They are never logged.
- Public deployments must terminate HTTPS at a reverse proxy and keep the API off unauthenticated plain HTTP.

## Server setup

1. Create a knowledge base and choose `MarginNote 4`.
2. Open the knowledge base settings and generate a pairing code.
3. Keep this value available:

   ```text
   https://your-deeptutor-host|PAIRING_CODE
   ```

4. Build or download `DeepTutorMarginNote4.mnaddon` and install it in MarginNote 4.
5. Open a notebook or document in study mode, tap the add-on command icon for DeepTutor, paste the
   value into the in-app pairing panel, and choose `Pair`.
   The add-on claims the token and starts a full snapshot. If a compatible pairing value is already
   on the clipboard, the dialog offers it as the initial value.

Build the add-on package from the repository root:

```bash
python3 scripts/build_marginnote4_addon.py
```

The package embeds a hash-locked AddonLib runtime from the MIT-licensed
`marginnoteapp/AddonLib` fork. Build-time provenance is recorded in
`packaging/addonlib.lock.json` and copied into the `.mnaddon` archive. DeepTutor
uses AddonLib's public MarginNote and network wrappers; DeepTutor-specific
pairing and sync logic stays in its own entry files.

## Device operations

- Tap the DeepTutor command to sync immediately.
- Copy `DeepTutor full resync` and tap the command to replace the server mirror from a complete new snapshot.
- Copy `DeepTutor revoke` and tap the command to remove local credentials.
- Revoke the device in the DeepTutor settings as well; local removal alone does not invalidate the token server-side.

Incremental batches are idempotent. If the cursor is stale, the add-on starts a complete snapshot automatically. Partial full snapshots remain invisible until every batch commits.

## Operations

- Device registry: `<DEEPTUTOR_HOME>/data/user/marginnote4/registry.db`
- Library data: `<owner workspace>/user/marginnote4/<library>.db`
- Back up both files, or revoke and run a full resync after restoring only configuration.
- The SQLite stores use WAL mode. Include `-wal` and `-shm` files in hot backups.
- The first full sync may take longer; subsequent syncs compare local hashes and upload only changed or deleted objects.

Production support requires validation on a real macOS or iPadOS MarginNote 4 installation. Without that device evidence, the platform must remain marked experimental.
