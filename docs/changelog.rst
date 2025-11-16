# Changelog
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2025-11-14
### Added
- PostgreSQL shared storage for distributed applications
- CLI tool for database setup (`resilient-circuit-cli pg-setup`)
- Support for environment variable configuration
- Optimized database schema with proper indexing
- Row-level locking for atomic operations
- Documentation for Read the Docs
- Apache 2.0 license

### Changed
- License changed from MIT to Apache 2.0
- Database schema optimized for performance
- Migration to new storage abstraction layer
- Improved error handling and logging

## [0.2.0] - 2025-11-10
### Added
- Complete rewrite of documentation with new examples
- Integration with Highway Workflow Engine
- Enhanced API for better developer experience
- Comprehensive usage examples and best practices

## [0.1.0] - 2023-06-15
### Added
- Initial release
- Circuit breaker pattern implementation
- Retry pattern with exponential backoff
- Basic decorator functionality