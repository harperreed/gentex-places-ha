<!-- ABOUTME: Records narrow, approved exceptions to the dependency audit gate. -->
<!-- ABOUTME: Each exception fails closed when its package or findings change. -->
# Security risk exceptions

## Home Assistant cryptography pin

- Approved by: Doctor Biz
- Approved on: 2026-08-20
- Package: `cryptography==48.0.1`
- Findings: `PYSEC-2026-3552`, `PYSEC-2026-3553`, and `PYSEC-2026-3554`
- Source of pin: `homeassistant==2026.8.1`
- Scope: local and CI dependency audits for this integration repository
- Removal trigger: Home Assistant moves to a supported release that resolves these
  findings, or the installed package version or audit finding set changes

The repository does not override Home Assistant's exact dependency pin. The canonical
check prints the approved findings and passes only when the package, version, and full
finding set match this entry. Any other result fails the check and requires review.
