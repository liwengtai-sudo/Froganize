## Summary

<!-- What user or maintainer problem does this change solve? -->

## Changes

<!-- List the focused behavioral, code, documentation, or visual changes. -->

## Safety and privacy

<!--
Answer explicitly:
- Can this change move, rename, inspect, reveal, or restore files?
- Does it widen a Desktop/workspace/Timeline or HTTP trust boundary?
- Does it affect symlinks, conflicts, snapshots, history, or undo?
- Does it read file contents, add persistence, or add network behavior?
Use "No impact" only after reviewing these questions.
-->

## Verification

<!-- Include exact commands and results. Use only temporary synthetic files. -->

- [ ] `python -m pytest`
- [ ] `python -m build`
- [ ] New or changed behavior has focused regression tests.
- [ ] Manual testing, if performed, used a disposable synthetic sandbox.

## Visual changes

<!-- Add before/after screenshots for UI changes. Redact all private data. -->

Not applicable.

## Documentation

<!-- List updated requirements, architecture, privacy, security, or user docs. -->

## Checklist

- [ ] The change is focused and matches the documented product direction.
- [ ] Assessment remains read-only and execution requires an explicit
      **Collect Desktop** action using the exact saved plan.
- [ ] Existing files cannot be overwritten.
- [ ] Tests do not access a real Desktop, home, Downloads, or Documents.
- [ ] No personal paths, histories, user files, secrets, or tokens are included.
- [ ] User-visible behavior and the changelog are updated where appropriate.
- [ ] Meaningful images have alt text and visual assets have clear provenance.
