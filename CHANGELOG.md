# Changelog
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
## [0.1.7] - 2022-11-14
### Changed
-  Updated to use GCP Artifact Registry


## [0.1.6] - 2022-10-19
### Removed
-  Removed safety from requirements


## [0.1.5] - 2022-03-22
### Added
- Added on_state_change argument accepting lambda to `CircuitBreakerPolicy`


## [0.1.4] - 2022-03-21
### Changed
- Renamed directory according to convention
- Migrated CI to the New Projects Structure


## [0.1.3] - 2022-03-03
### Added
- Added on_sate_changed hook to the `CircuitBreakerPolicy`
### Changed
- `highway_circutbreaker.circuit_breaker.State` is available under `highway_circutbreaker.CircuitBreakerState`
- CircuitBreaker now exposes call history


## [0.1.2] - 2022-02-23
### Added
- Documentation


## [0.1.1] - 2022-02-23
### Changed
- Failsafe accepts empty sequence of Policies
- Policy is accessible from the package root under `highway_circutbreaker.Policy`


## [0.1.0] - 2022-02-22
### Added
- Initial release
