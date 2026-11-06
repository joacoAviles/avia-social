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

## Own-business authorization — 2026-11-05

Meta's Facebook Login for Business requirements explicitly require the app-owner
portfolio to be separate from the client portfolio for business-integration
system-user tokens. This requirement was missed in the earlier onboarding guide:
https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business
(Requirements under Business Integration System User Access Tokens).

For an installation connecting its own business assets, prepare a separate
USER-token configuration, keep Unified Login for eligible client portfolios,
and use the Facebook / Instagram-via-Facebook connectors. The Instagram variant
requires a professional Instagram linked to a Page administered by the person
logging in. Do not move assets, delete grants or change the existing Unified
configuration just to test this alternative.

Register both exact HTTPS callbacks in Facebook Login for Business settings:
- `/social-accounts/callback/facebook/`
- `/social-accounts/callback/instagram/`

These differ from `/callback/instagram_login/` and `/callback/instagram_unified/`.
The trailing slash must match AVIA's generated redirect URI.

Live investigation: an independent USER configuration was saved, credentials were
prepared for the previously unconfigured Facebook and Instagram connectors, and
both callbacks were registered. The initial blocked-redirect error was cleared.
However, Meta's OAuth dialog then rendered "Sorry, something went wrong" before
returning an authorization code. A reload and a v27 dialog check did not resolve
it. No account connection or publishing success is claimed. This does not prove a
provider-wide outage or establish that portfolio ownership was the only cause of
the previous empty-account response. Do not repeat login indefinitely or show a
connected state before actual account discovery and selection succeed.
