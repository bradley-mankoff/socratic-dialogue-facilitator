# 01 — Free self-host URL while this Mac is on

Type: research
Status: resolved
Blocked by: none

## Question

Given Tailscale's 14-day trial is burned (user ground truth — treat as unavailable/paid), what free self-host path gives multiple parties one URL to a live board while this Mac is on?

Survey LAN + QR, Cloudflare Tunnel free tier, ngrok free tier, Tailscale personal free vs trial state, plain localhost + screen-share fallback. For each: cost, account needed, URL stability, same-WiFi vs anywhere, trust/auth implications. Recommend one default + one fallback for the Justice fixture test. Fixture: two friends on phones/laptops joining a board hosted here.

## Answer

Findings: `.scratch/socratic-facilitator/research/host-substrate.md` on branch `research/host-substrate`.
Gist: Cloudflare Quick Tunnel is the default — $0, no account, one command (`cloudflared tunnel --url http://localhost:PORT`) yields a public HTTPS `*.trycloudflare.com` URL anyone can open; caveats are a rotating URL (re-QR each session), no SSE support (use WebSocket/polling), and dev-only SLA. Fallback is LAN + QR (same-WiFi, zero third parties), with localhost + screen-share as last resort. ngrok free loses (account + browser interstitial on HTML); Tailscale Personal is $0 free-forever independent of the burned Premium trial but excluded per ground truth.
