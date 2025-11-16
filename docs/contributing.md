# Contributing to Resilient Circuit

Thank you for your interest in contributing to Resilient Circuit! This document provides guidelines and information about contributing to the project.

## Table of Contents
1. [Getting Started](#getting-started)
2. [Development Setup](#development-setup)
3. [Code Style](#code-style)
4. [Testing](#testing)
5. [Documentation](#documentation)
6. [Submitting Changes](#submitting-changes)
7. [Code of Conduct](#code-of-conduct)

## Getting Started

Resilient Circuit is part of the Highway Workflow Engine ecosystem and follows established patterns for Python library development. Before contributing:

1. Fork the repository on GitHub
2. Clone your fork locally
3. Check the issue tracker for existing issues or create a new one for significant changes
4. Discuss your proposed changes before beginning implementation

## Development Setup

### Prerequisites

- Python 3.9 or higher
- pip package manager
- Git

### Installation

1. Clone your fork:
```bash
git clone https://github.com/YOUR_USERNAME/resilient_circuit.git
cd resilient_circuit
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the package in development mode:
```bash
pip install -e ".[dev]"
```

### Running the Project

The library is designed to be used as a dependency, but you can run tests to verify your setup:

```bash
python -m pytest
```

## Code Style

Resilient Circuit follows established Python community standards:

### Formatting

- Use [Black](https://github.com/ambv/black) for code formatting
- Use [isort](https://github.com/PyCQA/isort) for import sorting
- Line length: 88 characters
- Use type hints where possible

### Linting

- Use [Ruff](https://github.com/charliermarsh/ruff) for linting
- Follow PEP 8 guidelines
- Address all linting warnings before submitting

### Type Hints

All public APIs should be properly typed. We use:
- `from typing import ...` for standard types
- `from typing_extensions import ...` for newer typing features
- Proper generic type annotations

### Naming Conventions

- Use `PascalCase` for class names
- Use `snake_case` for function and variable names
- Use `UPPER_CASE` for constants
- Follow descriptive naming practices

## Testing

### Test Structure

Tests are located in the `tests/` directory and follow pytest conventions.

### Running Tests

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=resilient_circuit

# Run specific test file
python -m pytest tests/test_specific.py
```

### Writing Tests

1. Place tests in the appropriate module in the `tests/` directory
2. Use descriptive test names that explain the expected behavior
3. Test both success and failure scenarios
4. Use pytest fixtures for common test setup
5. Follow the Arrange-Act-Assert pattern

### Test Coverage

Strive for high test coverage, especially for:
- All public API functions and methods
- Error handling paths
- Edge cases and boundary conditions
- Different configuration options

## Documentation

### API Documentation

- Document all public classes, functions, and methods
- Use docstrings that follow the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- Include type hints and parameter descriptions

### Examples

Include practical examples in documentation that demonstrate:
- Basic usage patterns
- Advanced configuration options
- Common integration scenarios

### README Updates

When adding new features:
- Update the README with new usage examples if applicable
- Ensure examples are tested and functional

## Submitting Changes

### Pull Request Process

1. Ensure your code follows the style guidelines
2. Add tests for new functionality
3. Update documentation as needed
4. Run all tests to ensure they pass
5. Commit your changes with clear, descriptive commit messages
6. Push to your fork
7. Create a pull request to the main repository

### Commit Messages

Write clear, descriptive commit messages that follow these guidelines:
- Use the imperative mood ("Add feature" not "Added feature")
- Limit the first line to 72 characters or less
- Reference issues and pull requests when applicable
- Include motivation and context when needed

### Code Review

All submissions require review. During review:
- Be responsive to feedback
- Make requested changes promptly
- Discuss alternative approaches if you disagree with suggestions
- Ensure all continuous integration checks pass

## Quality Standards

### Performance

- Avoid unnecessary performance regressions
- Profile code if performance changes are significant
- Consider the impact on the calling code's performance

### Compatibility

- Maintain backward compatibility when possible
- Clearly document breaking changes
- Follow semantic versioning principles

### Error Handling

- Provide clear, actionable error messages
- Use appropriate exception types
- Ensure error handling doesn't mask important issues

## Code of Conduct

This project adheres to the Python Community Code of Conduct. By participating, you are expected to uphold this code.

### Our Pledge

In the interest of fostering an open and welcoming environment, we pledge to:
- Be respectful of differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community
- Show empathy towards other community members

### Our Standards

Examples of behavior that contributes to creating a positive environment:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what is best for the community

Examples of unacceptable behavior:
- Trolling, insulting/derogatory comments, and personal attacks
- Public or private harassment
- Publishing others' private information without explicit permission
- Other conduct which could reasonably be considered inappropriate

## Questions?

If you have questions about contributing, feel free to:
- Open an issue on GitHub
- Check the existing documentation
- Look for similar patterns in the existing codebase

Thank you for your contribution to Resilient Circuit!