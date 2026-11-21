# Installation regression lesson — case aliases

The first 0.9.2 candidate passed Windows/Linux tests but failed rollback of
lowercase `cadwiz` on the Mac CI filesystem. `PosixPath` compares path spelling
case-sensitively even when APFS resolves both spellings to the same directory;
WindowsPath equality masked the bug. Compare existing filesystem identity with
`Path.samefile`, and preserve the original spelling in rollback records.

Guard: `test_clean_upgrade_and_rollback_preserve_user_files[cadwiz]` on native
macOS, Windows and Linux. Fast path: run `tests/test_installation_recovery.py`,
then the native Mac workflow. Copied files and simulated names do not establish
APFS compatibility or successful GUI startup. Keep publication gated on evidence.

Evidence: initial failing Mac check run 44921534509, 2026-11-21. The correction
remains subject to the subsequent native check results. No production installer
was replaced with the failed candidate.
