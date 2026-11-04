# Unrestricted policy patch

`RestrictedFeaturePolicy.cs` is the shared replacement for release rebuilds and
the custom development branch. It preserves `Assess()` for diagnostics, returns
false from `IsRestricted`, allows `Check()`, and makes `ThrowIfRestricted()` a
no-op. The upstream WPF `IRestrictedFeatures` adapter forwards to these methods,
so Core launch and modpack operations use the same unrestricted policy.

Reviewed against upstream dev `16207f9ee5db003f9683e46bc4a938c88509a3f9`.
`reviewed-policy-current.cs` records that upstream policy for regression tests.
Earlier reviewed policy blobs remain accepted for exact release-tag rebuilds.

Both automation paths reject unreviewed upstream policy blobs. Branch sync
resolves conflicts only in the reviewed policy file and aborts on other
conflicts. It checks the existing custom policy before merging and never
force-pushes. Future upstream policy changes require reviewing the policy,
its callers and the Core adapter before updating the accepted hashes.

Run checks with:

```sh
python3 -m unittest discover -s .github/release-sync -p 'test_*.py'
```
