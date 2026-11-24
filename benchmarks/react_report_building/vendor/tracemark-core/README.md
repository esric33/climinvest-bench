# Frozen TraceMark compiler snapshot

`document-engine.js` is a benchmark-local snapshot of the compiler from
`climinvest-studio` commit `ca2c092`. The benchmark intentionally vendors the
exact compiler used to build its gold contract so later application refactors
cannot silently change an experiment release.

Update this file only as an explicit benchmark-version change, then rebuild
and validate the gold manifests. Redistribution remains subject to the owner’s
application-code license decision.
