# Personal Meeting Assistant setup with Sekisho audio passthrough

Sekisho exposes Foundry OpenAI-compatible audio routes through the same `/openai/*` gateway path used for chat and responses. Personal Meeting Assistant can use its Custom STT provider with a cURL template pointed at Sekisho.

```bash
curl -X POST "https://<sekisho-fqdn>/openai/v1/audio/transcriptions" \
  -H "Authorization: Bearer {{API_KEY}}" \
  -F "file=@{{AUDIO}}" \
  -F "model=gpt-4o-mini-transcribe" \
  -F "language={{LANGUAGE}}"
```

- `{{AUDIO}}` is the captured audio file path provided by Personal Meeting Assistant.
- `{{API_KEY}}` is a Sekisho Key for the gateway. It is never a Foundry key.
- `{{LANGUAGE}}` is the language hint Personal Meeting Assistant passes to transcription.

The synchronous OpenAI-compatible `/audio` API has a 25 MB file limit. For OpenAI-audio clients that support text-to-speech, use the TTS model `gpt-4o-mini-tts` through `/openai/v1/audio/speech`.
