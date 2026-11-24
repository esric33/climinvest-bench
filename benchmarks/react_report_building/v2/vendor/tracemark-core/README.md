# Pinned TraceMark compiler for benchmark v2

These files are an exact benchmark-local snapshot from sibling repository
`climinvest-studio` at commit:

`28b49429da5befbe22d9debd1f72ac7e3c10b2c0`

Pinned file hashes (SHA-256):

- `document-engine.js`: `eb2f4855dcdcab76d951e43b8f40ababe4584423856e0f494ef7b1131263d655`
- `report-ir.js`: `ef4c791b8ce41bce0e6bbf63e098fa79c16dea6681bd5b1b0063ba39128ba6db`

`compile_contract.js` verifies these hashes before compiling. Updating either
file is therefore an explicit benchmark-version decision: update the pin,
rebuild the compiled contract, and rerun validation rather than silently
following Studio's working tree.
