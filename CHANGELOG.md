# Changelog

## numeric_v1.1 experiment - 2026-10-15

### Added

- Run the separately frozen numeric_v1.1 forecaster with covariance-normalized filtered historical simulation and the existing recovery and optional text-hook contract.
- Compare all 15 precommitted alternatives using C1, complete per-card scores, year-block confidence intervals, and a five-page results report. Small mean gains do not establish robust improvement; historical capped cards rise from 23 to 24.
- Publish amd64 images through `numeric-v1.1-*` CI tags with a separate `numeric_v1_1` GHCR tag and anonymous-pull verification.

### Changed

- Default the CLI to numeric_v1_1 while preserving explicit numeric_v1 and M0 selection, old frozen files, and the old image workflow's numeric_v1 default.

## [0.1.0.0] - 2026-10-14

### Added

- Generate joint numeric forecasts with the published Track 2 M0 baseline and an offline inference image.
- Compare M0, the reference CLI, and custom forecasters using historical backtests, practice proxy labels, calibration checks, and official admissibility gates.
- Reproduce the 2,060-card baseline measurement with pinned dependencies, setup commands, tests, and documented data provenance.
- Read measured scores, breakdowns, and limitations in the baseline tables and results PDF.
- Download the complete generated evaluation snapshot with a per-file SHA-256 manifest and restoration instructions.
