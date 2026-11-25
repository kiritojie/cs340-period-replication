# Pinned PERIOD source snapshots

Repository: https://github.com/wcventure/PERIOD

Commit: `b6f72a7b06d01ffa7114b640312873ec2578a5ea`

These are unchanged upstream source bytes, including their original line endings.
`SOURCE_MANIFEST.json` records each original repository path, byte length,
SHA-256 and Git blob SHA-1. The DBDS module blobs were checked against the
official GitHub directory metadata when retrieved. Runtime source, build rules,
and compiler-wrapper source are inspection evidence only; they are not compiled
or installed by the comparison scripts.

The upstream MIT license and copyright notice are preserved in `LICENSE`.
This README and the source manifest are local provenance documentation.

The runtime source declares 3964 entries for each key-point data array; the
current upstream Python driver addresses 1990 entries. No source constant is
changed to hide that difference. A live experiment must inspect the actual
executable and existing runtime object's DWARF, and stops if their layout cannot
be proven compatible with the driver.

Offline tests import only the dependency-free generator modules from here.
Actual experiments use the fixed, hash-verified modules in the existing PERIOD
container, not a replacement runtime or a rebuilt benchmark.
