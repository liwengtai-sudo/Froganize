# Froganize Screenshot Intelligence

This directory contains the complete Swift source for Froganize's optional
Screenshot Intelligence component. It is part of the main repository and is
built into the unified macOS prototype as a nested menu-bar application.

The component watches only a folder chosen by the user, recognizes supported
macOS screenshot names, sends matching images to the explicitly configured AI
provider after upload consent is enabled, and delegates every rename/undo to
the Python `froganize-fileops` safety helper.

## Requirements

- macOS 13 or newer;
- Swift 5.9 or newer;
- Command Line Tools or Xcode;
- Python helper installed from the repository root for end-to-end mutation
  tests.

No third-party Swift package is required.

## Build and self-test

From this directory:

```bash
swift build --disable-sandbox
swift run --disable-sandbox ScreenshotRenamerSelfTest
./Scripts/check-keychain-access-policy.sh
```

Build the standalone local app:

```bash
./Scripts/build-app.sh
```

The output under `build/` is ignored and is not a public release artifact.

## End-to-end helper test

After installing the Python project from the repository root:

```bash
FROGANIZE_E2E_HELPER="$(cd ../.. && pwd)/.venv/bin/froganize-fileops" \
  swift run --disable-sandbox ScreenshotRenamerSelfTest
```

The self-test uses synthetic files in the operating system's temporary
directory. It does not require a real API key and does not contact an AI
provider.

## Privacy and credentials

- Processing and uploads are disabled by default.
- Saving settings or opening the panel does not contact a provider.
- A real request occurs only for an explicit connection test or enabled
  processing of a matching screenshot.
- Packaged credentials are stored in macOS Keychain.
- API keys are not written to repository files, activity history, or the Python
  JSON file-operation protocol.
- Custom providers must use an HTTPS OpenAI Chat Completions-compatible
  endpoint without embedded credentials, query parameters, or fragments.

This source is distributed under the repository's MIT License. Apple system
frameworks remain subject to Apple's terms.
