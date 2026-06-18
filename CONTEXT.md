# Sekisho Context

## Glossary

- **Foundry**: Microsoft Foundry's OpenAI-compatible data-plane endpoint, normally shaped like `https://<resource>.openai.azure.com/openai/v1/`, with local key authentication disabled and Microsoft Entra authentication required.
- **Gateway**: Sekisho, a thin managed-identity reverse proxy that accepts OpenAI-compatible client traffic, validates a Sekisho Key, swaps outbound auth to an Entra bearer token, and forwards payloads unchanged to Foundry.
- **Key**: A simple bearer credential presented by gateway callers. Keys are named, independently rotatable, and revocable. A Key is not a Foundry key and never grants direct Foundry access.
- **Rotation**: Replacing a named Key's current value with a new cryptographically strong value while optionally keeping the previous value valid for a short grace window.
- **Anonymous Mode**: An explicit development/demo mode that disables inbound Key validation so requests can pass through without a bearer Key. It is off by default.
