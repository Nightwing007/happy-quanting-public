# Deploying Happy Quanting

The backend runs on a **Hugging Face Space** (a free Docker host), the frontend on **Vercel**. The
browser only ever talks to the Vercel domain; Next.js forwards `/api/*` to the Space on the server
side (`frontend/next.config.ts`), so there is no CORS setup and the login cookie stays first-party.

```
browser -> https://<project>.vercel.app  (Next.js)  -- /api/* -->  https://<owner>-<space>.hf.space  (FastAPI)
```

Do the backend first, because the frontend needs its address.

## What you need

- A Hugging Face account (huggingface.co, free) and a **write** access token: Settings -> Access Tokens -> New token -> role "Write". Copy it once; it is your git password.
- A Vercel account (vercel.com, free "Hobby"), signed in with the GitHub account that holds this repository.
- This repository pushed to GitHub.
- `git` on your machine.

## 1. Backend on Hugging Face Spaces

### Create the Space

1. huggingface.co -> your avatar -> **New Space**.
2. Name: for example `happy-quanting-api`. License: any. SDK: **Docker**, template **Blank**. Hardware: **CPU basic, free** (2 vCPU, 16 GB RAM). Visibility: **Public** (a private Space needs a token on every request, which the Vercel proxy does not send).
3. Create. The Space is its own git repository at `https://huggingface.co/spaces/<owner>/<space>`. It expects a `Dockerfile` and a `README.md` with a small header at its **root**. Both already sit in `backend/` (`backend/Dockerfile`, `backend/README.md` with `sdk: docker` and `app_port: 7860`), so push only that folder.

### Push only `backend/`

From the repository root, once (subtree push, keeps the Space's history separate from yours):

```
git remote add space https://huggingface.co/spaces/<owner>/<space>
git subtree split --prefix=backend -b hf-deploy
git push space hf-deploy:main --force
```

Git asks for a user name (your Hugging Face user name) and a password (paste the **token**). `--force` is right here: the Space's history is just a copy of `backend/`. Only committed files are pushed, so commit `backend/` first, and `.venv`, `.env` and `data/` (all git-ignored) never leave your machine.

To update later: `git branch -D hf-deploy`, then the same `split` and `push` lines.

If you do not want to use subtree, copy the folder instead (PowerShell):

```
git clone https://huggingface.co/spaces/<owner>/<space> hq-space
robocopy backend hq-space /E /XD .venv data tests __pycache__ .pytest_cache .ruff_cache /XF .env
cd hq-space; git add .; git commit -m "Backend"; git push
```

(`robocopy` exit codes 0 to 7 mean success.)

### Variables and secrets

Space -> **Settings** -> **Variables and secrets**. Add these as **Variables** (they are not secret) and restart the Space after changing them:

| Name | Value | Why |
|---|---|---|
| `COOKIE_SECURE` | `true` | The session cookie is only sent over HTTPS. Required in production. |
| `HOSTED_MODE` | `true` | Refuses uploaded and editor code, caps sandbox processes, tells the frontend. |
| `MARKET_DATA_PROVIDER` | `yahoo` | Live prices. Use `fake` for the fallback below. |
| `SEED_DEMO_MARKETPLACE` | `true` | Creates the five demo creators and measures their listings at start. |
| `BASE_CURRENCY` | `INR` | The account currency. |
| `TRUST_PROXY_HEADERS` | `true` | Behind Vercel every request comes from Vercel's servers; this makes the login limiter use the forwarded client address (see "Things to know"). Never set it on a server reachable without the proxy. |
| `MAX_SANDBOXES` | `8` | Most sandbox child processes at once. The seeded listings are uploaded-style code, so every marketplace subscription holds one child for as long as it runs; the default of 2 would stop a third subscriber. The free Space has 16 GB and a child is about 90 MB. |
| `DATABASE_URL` | leave unset | The image defaults to `sqlite:////tmp/happy-quanting.db`. Set it as a **Secret** only if you use the Postgres option below. |

The first build takes several minutes (Space page -> the **App** tab shows "Building"). When it says **Running**, check `https://<owner>-<space>.hf.space/api/health`; it should answer `{"status":"ok", ... "hosted_mode":true}`. (The address is your user name and the Space name, lower-case, joined with a dash. The Space page's "Embed this Space" menu shows it as "Direct URL".)

### The demo password

On every fresh start the server creates the `demo` user and prints the password **once**:
Space -> **Logs** -> **Container** tab -> look for

```
=====
Demo login: demo / k82OqZLACnRP  (shown once)
=====
```

Only you, the owner, can read the logs. If you missed it, restart the Space (Settings -> Restart), which starts from an empty database and prints a new one. Anyone can also just sign up at `/signup`.

### Things to know

- **The disk resets.** On the free tier the container's disk is empty at every start, so the database lives in `/tmp` and **everything (accounts, trades, sims, the seeded marketplace) is gone after a restart or sleep**. The demo marketplace is rebuilt at start, but its performance numbers take a few minutes to measure again, and the demo password changes. Persistent storage (mounted at `/data`, with `DATABASE_URL=sqlite:////data/app.db`) is a paid Space option.
- **Sleeping.** A free Space goes to sleep after a couple of days without visits (Hugging Face sets the exact period). The first visit wakes it, which takes about a minute plus the seed. **Wake it before a demo**: open `https://<owner>-<space>.hf.space/api/health` a few minutes early, then wait for the marketplace to fill (below). A wake-up also empties the database (see above).
- **Login limiter and client addresses.** With `TRUST_PROXY_HEADERS=true` the client address is the first entry of `X-Forwarded-For`, else `x-vercel-forwarded-for`, else `X-Real-IP`, else the socket address. 5 wrong passwords for one username from one address lock that pair for 15 minutes; other addresses are unaffected. Separately, 20 failures for a username across all addresses in 15 minutes make every attempt on it wait 2 seconds (a slow-down, never a lockout), so nobody can lock `demo` out for everyone. Not verified against a live deployment: Vercel's docs say it overwrites `X-Forwarded-For` with the real client and equals `x-vercel-forwarded-for`, but do not say an external rewrite forwards either to the origin. After deploying, wrong-password from two networks should lock only one; if both are locked together, the header is not arriving and the limiter falls back to Vercel's shared address (the old behaviour). Leave the setting off for local development: a directly reachable server would let callers spoof the header.
- **Hosted mode** removes the code editor's reach, not the page: until the frontend hides it, an upload or a code block answers "Uploading or running your own code is turned off on this public server." (403, code `disabled_in_hosted_mode`). Library algorithms, the lab, block graphs without code blocks and the seeded marketplace listings all work.
- **Postgres (optional, untested).** To keep data across restarts for free you could create a database at neon.tech, add `psycopg[binary]` to `backend/requirements.txt`, and set the Space **secret** `DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>/<db>?sslmode=require`. This has not been tried here; the migrations were written and tested on SQLite only, so treat it as an experiment and keep the SQLite default for the hackathon.

## 2. Frontend on Vercel

1. vercel.com -> **Add New...** -> **Project** -> import the GitHub repository.
2. **Root Directory**: click Edit and choose `frontend`. **Framework Preset**: Next.js (detected). Leave build and output settings alone.
3. **Environment Variables**: add `BACKEND_URL` = `https://<owner>-<space>.hf.space` (no trailing slash, no `/api`). It is read when the site is **built**, so if you change it later, redeploy.
4. **Deploy**. The build takes a few minutes.

### After deploying, check

1. Open the Vercel address. The "backend is not reachable" banner must **not** show. (If it does, `BACKEND_URL` is wrong or the Space is asleep: open the Space address, wait, reload.)
2. Sign up with a new user name. You land on the dashboard (this proves the proxy and the cookie).
3. Reload the page: you are still logged in. Log out and in again.
4. Search a symbol (for example `AAPL` or `RELIANCE.NS`), open it and place a small buy. Open **Orders** and see it filled or waiting with a reason.
5. Open **Marketplace**: five listings with numbers (they may say "measuring" for a few minutes after a Space start).
6. Open **Create**: with hosted mode on, the editor and upload are not available (see the follow-up in "What the frontend still needs" below).

### Cookies and the proxy (checked)

`backend/app/api/auth.py` sets `hq_session` with `path=/`, `SameSite=Lax`, `HttpOnly`, `Secure` when `COOKIE_SECURE=true`, and **no Domain attribute**, so the browser stores it for the Vercel domain. Next.js passes the backend's `Set-Cookie` back and the browser's `Cookie` forward through the rewrite, so everything stays first-party. Nothing needs changing. One caution: with `COOKIE_SECURE=true` the cookie is dropped on plain `http`, so local development must keep it `false`.

## Fallbacks

- **Yahoo blocks or throttles the Space** (cloud IPs sometimes get rate-limited; symptoms: quotes fail, charts empty, "data unavailable"): set `MARKET_DATA_PROVIDER=fake` in the Space variables and restart. Prices become deterministic made-up data, and the header shows the "Offline demo data" tag. Everything else works.
- **Cold start right before the demo**: open the Space address ten minutes early, watch the Logs tab until "Application startup complete", then log in once and open Marketplace to confirm the listings have numbers.
- **Lost the demo password**: sign up a new user; or restart the Space and read the new one from the logs.

## Hackathon checklist

- [ ] Space is **Running**, `/api/health` shows `"hosted_mode": true` and `"data_source": "yahoo"` (or `fake` on purpose).
- [ ] Variables set: `COOKIE_SECURE=true`, `HOSTED_MODE=true`, `SEED_DEMO_MARKETPLACE=true`, `TRUST_PROXY_HEADERS=true`, `MAX_SANDBOXES=8`.
- [ ] Vercel `BACKEND_URL` points at the Space, the site was redeployed after setting it.
- [ ] A fresh sign-up works, survives a reload, a trade fills.
- [ ] Marketplace shows five listings with measured numbers.
- [ ] Demo password noted from the Logs (or a pre-made account you know).
- [ ] The Space was woken within the last hour (it empties on a restart, so make your demo data **after** the last wake).
- [ ] Fallback ready: you know where to flip `MARKET_DATA_PROVIDER=fake`.
- [ ] Both addresses are saved somewhere you can reach from the stage laptop.

## What the frontend still needs (for the next frontend step)

- Read `hosted_mode` from `GET /api/health` (`useHealth`) and hide the code editor (`/create/editor`), the upload page (`/create/upload`), the code block kind in the block editor ("New code block", code custom blocks) and the "run my code" options in the sim, backtest and deploy pickers when it is true. The server already refuses them with 403 `disabled_in_hosted_mode`; show that sentence if it still arrives.
- `frontend/src/lib/types.ts` `Health` needs `hosted_mode: boolean`.

## Memory (measured locally, Windows, real Yahoo data)

Whole process tree (uvicorn plus sandbox children). The 16 GB tier is nowhere near a limit.

| Moment | Working set |
|---|---|
| Idle after the seed | about 390 MB |
| Daily library backtest | about 410 MB |
| Backtest of source (one sandbox child, about 90 MB) | about 360 to 420 MB |
| Two deployments running, library algorithms (hosted mode) | about the idle figure |
| Two deployments running, uploaded code (two children; not possible in hosted mode) | about 540 MB |
