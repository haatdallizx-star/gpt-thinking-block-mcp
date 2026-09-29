# Security

This project is self-hosted software distributed under the MIT license, provided as-is and without warranty of any kind. No hosted service, shared endpoint, or managed deployment is operated by this project.

## Scope

The bundled server is a reference implementation of the thinking block renderer: minimal, dependency-free, and bound to loopback by default. It is provided to demonstrate the renderer, not as a hardened service.

## Deployment

Each installation is deployed and operated independently. Network exposure, transport security, authentication, and access control are properties of a given deployment and remain the responsibility of the party operating it.

## Data handling

Thinking capture is disabled by default. When enabled, captured content is written in plain text and should be handled accordingly, as should any credentials or private URLs associated with a deployment.

## Reporting

Security observations are welcome as public issues.
