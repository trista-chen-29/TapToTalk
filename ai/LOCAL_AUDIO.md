# Local-first phrase speech

`speak(phrase_id, text)` checks the current profile and language catalog, rejects
unknown/unsafe IDs, and tries `bridge/audio/<phrase_id>.wav` before loading any API
key or calling Cartesia. Resolved paths must remain inside the audio directory.
Audio-off and screen-only profiles produce no audio or network calls.

English clips are the only current cached language set. Other-language profiles
must have a matching catalog and never use the English cached recordings.
Missing or failed English clips use the existing Cartesia fallback; if that also
fails or there is no key, return without raising so the bridge can show text.
No audio files are generated or changed by this implementation.

## Verification

- Nine local-first tests use a synthetic catalog ID and mocked playback/API calls.
- Existing speech tests force missing clips; scaffold tests mock audio so routine
  tests never play the speaker or call the network.
- All 16 phrase and four category WAVs are present, readable, and nonempty.
- Actual `person_nurse.wav` completed through the existing Core Audio playback
  function with socket connect/connect_ex/create_connection blocked in-process,
  and API-key lookup and Cartesia synthesis forbidden. Wi-Fi settings were not
  changed during the agent check. The user subsequently reported all manual
  tests passed: pain_here and person_nurse through laptop speakers, Wi-Fi-off
  playback, temporary missing-clip fallback, audio-off/screen-only, and invalid IDs.
  Missing-clip manual fallback used a mocked Cartesia response, not a live call.
- 40 unittest tests, four standalone ranking regressions, and 24 frontend tests
  pass. Ruff lint/format, Python/JavaScript syntax and
  diff whitespace checks pass. SQL/query work on other branches is not included
  in this checkout's test count.

Install the speech dependencies listed in pyproject.toml before running speech.

## Integration limits

The helper is synchronous. Person 1 must invoke it off the bridge event loop and
retain text fallback when sound fails. It returns None and does not acknowledge
speech to the browser. No selection state-machine or UI protocol is changed.

The helper reads the on-disk profile. The bridge still needs to coordinate an
effective per-session settings snapshot so edits apply on the next session, as
specified in the contract. No profile fields or timing rules are changed here.

Category highlights use `speak_category`, which plays `cat_<category>.wav` and
does not accept those ids in `speak`. A highlight never calls Cartesia.
The user manually tested pain_here and person_nurse; the remaining files were
inspected as WAVs, not individually listened to. Real hardware, every profile's nurse-call flow, other
operating systems, and live Cartesia failure recovery are not end-to-end verified.
