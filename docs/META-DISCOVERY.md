# Meta account discovery audit — 2026-11-02

Metricool documents distinct direct-Instagram and Facebook-backed connections:
https://help.metricool.com/es/como-conectar-instagram-a-metricool-sermi
Postiz documents separate Facebook Business and Instagram Standalone flows:
https://docs.postiz.com/self-host/providers/instagram
Neither guide establishes that a legacy token flow can be substituted for Unified Login.

Meta Unified Login documents business-system-user discovery through
`/me?fields=client_business_id` and `/me/assigned_instagram_accounts?fields=id,username`:
https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/get-started

The diagnostic fallback uses Meta's documented token introspection:
https://developers.facebook.com/docs/graph-api/reference/debug_token/

When the primary edge is empty, validate token validity and app identity and require
instagram_basic. Inspect only granular-scope targets returned by Meta. Resolve
Instagram targets with the customer token; if none resolve, inspect explicitly
authorized Page targets for their linked Instagram account. Never enumerate owned
business assets with an app token, guess IDs, or insert a user-supplied account.
Each candidate must resolve to the expected identity. The app token is used only
for introspection. Missing targets remain an unresolved authorization, not success.

The existing picker remains the final selection step; connecting one account does
not replace another. Legacy tokens and credentials stay on their original paths.
Production diagnostics contain counts and validity flags, never raw responses,
tokens, secrets, usernames or authorization codes. Root production logging drops
INFO, so discovery diagnostics use WARNING.

Validation: 23 focused tests pass, including empty edges, wrong apps, invalid grants,
missing scope, target identity mismatch, authorized Page resolution and preservation
of existing accounts. These tests do not establish successful live authorization.
