# Credential remediation

Runtime credential literals and fallbacks were removed from R2/Modal, Gemini/Pexels, the legacy worker launcher, database defaults and YouTube configuration/debug scripts. Missing required credentials must be supplied through environment or the existing secret configuration. Diagnostic scripts no longer print R2 access key prefixes, signed URLs or raw SDK exceptions.

The tracked nested Chrome profile was removed from the Git index using `git rm --cached`; local files were retained. A recursive profile ignore rule prevents accidental re-addition. No repository history rewrite or remote credential rotation was performed.

Operator actions:

- Rotate exposed R2 access/secret; update both Render and local configuration, verify access, then revoke old credentials.
- Rotate exposed Gemini/Pexels keys and worker client secret where used.
- Rotate the YouTube OAuth client secret and revoke/re-authorize the exposed refresh token. Set a fresh OAuth state key through environment; old fallback is removed.
- Review any real database password previously using a source fallback and browser sessions whose data was tracked; revoke affected sessions as appropriate.
- Do not paste replacement values into chat, source, launcher scripts or command-line arguments.

Deleting current literals does not remove them from old Git commits. Credential revocation is essential; history cleanup needs a separate coordinated decision.

Security scan is a pattern-based text check, not a guarantee that every secret is absent. It scans the current Git index, not the stale `.git2` directory. Binary media is excluded from token regex checks because arbitrary binary bytes can mimic token patterns; generated media must not be staged in this change.
