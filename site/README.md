# ParkourFlux site

Static site for `parkourflux-policy.pages.dev`, built after TikTok rejected the
app's **Website URL** for being a policy/landing page rather than a developed
site.

No build step, no framework, no external requests — six HTML files and one
stylesheet. Every page works standalone.

| File | Path | Purpose |
|---|---|---|
| `index.html` | `/` | What ParkourFlux is, what it publishes, where to find it |
| `how-it-works.html` | `/how-it-works` | The production pipeline, guardrails, content standards |
| `tiktok.html` | `/tiktok` | **The page the reviewer cares about** — scopes, why each is needed, what data is stored, revocation |
| `privacy.html` | `/privacy` | Privacy policy |
| `terms.html` | `/terms` | Terms of use |
| `callback.html` | `/callback` | OAuth redirect target — displays the code to paste back |
| `style.css` | `/style.css` | Shared styles, light + dark |

## Placeholders — filled in

All three are done; kept here so it's obvious what to change if any of them move.

1. **Contact email** — `mindcraftkrish.patel@gmail.com`, in every footer and on
   the TikTok, privacy and terms pages. App review expects a working address.
2. **"Last updated"** — `August 6, 2026` on `/privacy` and `/terms`. Bump this
   whenever the policy text actually changes, not on every deploy.
3. **Instagram URL** — `instagram.com/parkourflux`, confirmed against the
   Graph API (`username: parkourflux`), not just the handle in `accounts.json`.

`grep -rn "REPLACE-WITH" site/` should return nothing.

## If you already have a privacy policy that TikTok accepted

Keep that text. Paste it into the `<main>` of `privacy.html` so it keeps the
new layout and navigation. Don't replace already-approved policy wording with
the draft here just because it's newer.

## The `/callback` route must not break

`tiktok_upload.py:23` hardcodes
`REDIRECT_URI = "https://parkourflux-policy.pages.dev/callback"`, and that exact
URL is registered in the TikTok developer portal.

- If your existing callback page works, **keep it** and drop the other files
  around it.
- If you deploy `callback.html` from here, it does the same job: reads `?code=`
  from the URL, shows it, offers a copy button. The code is never transmitted
  anywhere.
- **If you change the domain**, update it in *both* places — `tiktok_upload.py`
  and the developer portal — or authorisation breaks.

## Deploying to Cloudflare Pages

The repo is public, so Pages can build from it directly.

**Existing project** — point it at this repo, set:

- Production branch: `main`
- Build command: *(none)*
- Build output directory: `site`

**Or drag-and-drop** — upload the contents of `site/` in the Pages dashboard.
Fastest route if you just want it live.

Pages serves `foo.html` at `/foo`, so the nav links (`/how-it-works`,
`/tiktok`) resolve without any redirect rules.

## Resubmitting to TikTok

Once it's live, check the pages actually load, then resubmit with **Website
URL** pointing at the root (`https://parkourflux-policy.pages.dev/`) — not at
`/callback` and not at `/privacy`. The reviewer needs to land on the home page
and be able to navigate.

The site describes what the tool genuinely does: a single-operator, first-party
publisher for accounts we own. Keep the app description in the portal
consistent with `/tiktok`, since a mismatch between the two is its own
rejection reason.
