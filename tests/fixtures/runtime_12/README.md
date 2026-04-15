# Runtime 12 Fixture Notes

`data/runtime_12/` is the live runtime data used by Round 01 validation tests.

Known contract facts surfaced by the implementation:

- live normal CSV support is `1..10`
- live disaster CSV support is `1..10`
- `parameters.json` declares normal scenarios `1..10`
- `parameters.json` declares disaster scenarios `[1, 2]`
- the frozen default fixture remains the default `{1,2}` selection preset for both stages

Round 01.5 semantics:

- the raw package may expose more support than the default selection
- `parameters.json` support declarations are advisory manifest metadata
- CSV support is the binding raw-availability source for whether a selected scenario exists
- the disaster JSON/CSV mismatch must be surfaced explicitly in manifest metadata
- loading still succeeds under the default `{1,2}` selection because those selected scenarios exist in CSV
