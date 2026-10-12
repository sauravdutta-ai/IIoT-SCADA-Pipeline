# Contributing to IIoT-SCADA Pipeline

Thank you for your interest in contributing to the IIoT-SCADA Pipeline project! Contributions that improve reliability, maintainability, documentation, testing, and observability are welcome.

## Getting Started

### Prerequisites

- [Git](https://git-scm.com/install/)
- [Docker and Docker Compose]((https://www.docker.com/products/docker-desktop/))
- [Python 3.11](https://www.python.org/downloads/) or a compatible version supported by the project
- A local .env configuration based on [.env.example](.env.example)

### Set Up the Project

1. Fork or clone the repository.
2. Review **.env.example** and configure your local environment.
3. Follow the [README](README.md) instructions to generate the required certificates and MQTT credentials.
4. Build and start the services using Docker Compose.
5. Verify that the services start correctly and telemetry flows through the pipeline.

> **Do not commit .env files, passwords, private keys, or other secrets.**

## Making Changes

1. Create a feature branch from the main development branch.
2. Keep changes focused and consistent with the existing project structure.
3. Follow Python conventions and write clear, descriptive names.
4. Update documentation when changing configuration, architecture, or behavior.
5. Add or update tests when modifying application logic.
6. Run the available validation checks before submitting your changes.

## Validation

Run the project's configured checks, including the GitHub Actions workflow where available. The CI workflow validates Python syntax and the Docker Compose configuration.

For changes involving telemetry ingestion, MQTT, anomaly detection, or storage, also test the relevant behavior locally when practical.

## Pull Requests

Before submitting a pull request:

- Explain the problem and the proposed solution.
- Describe the changes made and how they were tested.
- Include screenshots when a change affects dashboards or other visual interfaces.
- Document any new environment variables or configuration requirements.
- Confirm that no secrets, credentials, generated private keys, or unrelated files are included.

## Reporting Issues

When reporting a bug, include the steps to reproduce it, expected and actual behavior, relevant sanitized logs, and your environment details. Remove credentials and sensitive information before sharing logs.

## Scope

This project is an engineering demonstration of an IIoT/SCADA telemetry pipeline. Contributions should not represent the system as safety-certified or production-ready without appropriate validation.

**Thank you for helping improve the project!**