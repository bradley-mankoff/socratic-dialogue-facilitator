# Host substrate: free self-host URL while this Mac is on

Ticket: `01-host-substrate` · Fixture X: Justice (Republic Book I) — two friends on phones/laptops join a board hosted on this Mac.
Ground truth: Tailscale trial burned → treat Tailscale as unavailable. Standing pref: self-hosted free.

## Comparison

| Path | Cost | Account? | URL stability | Reach | Trust / auth |
|---|---|---|---|---|---|
| LAN + QR (`http://<lan-ip>:PORT`, `.local` via Bonjour) | $0 | None | Unstable: DHCP IP changes per lease; `<host>.local` mDNS name is steadier but still LAN-only | Same Wi-Fi/LAN only | No TLS by default (plain HTTP → some browser APIs like mic/camera need secure context); anyone on the LAN can reach it; no third party in path |
| Cloudflare Quick Tunnel (`trycloudflare.com`) | $0 | None | Rotates: new random `*.trycloudflare.com` per `cloudflared` run, lives only while the process runs | Anywhere (public HTTPS URL) | Public URL — anyone with the link can load it unless the app adds auth; traffic proxied through Cloudflare; dev/test only, no SLA |
| ngrok free | $0 | Yes (authtoken) | Stable: one auto-assigned dev domain (e.g. `xxx.ngrok-free.app`) tied to the account, reused across restarts | Anywhere (public HTTPS URL) | Public URL with automatic TLS; free tier shows a browser interstitial page in front of HTML traffic (dismissable, 7-day cookie); 1 user, no custom domains |
| Tailscale (Serve / Funnel) | Personal $0 free forever — **but excluded per ground truth** | Yes + every guest needs client for Serve | Stable tailnet DNS (`*.ts.net`); Funnel gives a public URL | Serve: tailnet members only. Funnel: anywhere | Strongest story (WireGuard identity, ACLs), but every guest installs Tailscale for Serve; Funnel needs MagicDNS+HTTPS+policy setup — moot while Tailscale is off the table |
| localhost + screen-share | $0 | None (uses existing call app) | N/A — no URL | Anywhere a video call reaches | Minimal exposure (no inbound anything); guests are view-only unless remote-control is enabled |

## Details

### 1. LAN + QR
- Serve on `0.0.0.0:PORT`, print a QR encoding `http://<mac-lan-ip>:PORT`. Zero cost, zero accounts, zero third parties, lowest latency.
- Apple Bonjour (zero-configuration networking) provides `.local` discovery/publishing on the local network, which softens the DHCP-churn problem vs raw IPs — but it is still same-network-only ([Apple Bonjour](https://developer.apple.com/bonjour/)).
- Limits: fails the moment a friend is off the Wi-Fi; plain HTTP (fine for viewing a board; mic/cam capture would need a secure context — relevant to the transcription ticket, not this one).

### 2. Cloudflare Quick Tunnel (TryCloudflare)
- One command, no account, no DNS, no inbound ports: `cloudflared tunnel --url http://localhost:PORT` → random `https://<words>.trycloudflare.com` with HTTPS/DDoS/edge routing automatic ([Quick Tunnels docs](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/), [trycloudflare.com](https://trycloudflare.com/)). Outbound-only connection model — origin never takes inbound traffic ([how Tunnel works](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)).
- Hard limits that matter to us: **no Server-Sent Events support**, 200 concurrent in-flight requests → HTTP 429 past that, no SLA — "testing and development only" ([Quick Tunnels docs](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)). The SSE gap constrains the live-pipeline ticket: prefer WebSocket or polling while on Quick Tunnels.
- URL rotates every restart (new random subdomain each run; dies with the process), so re-print/re-QR the URL each session. A stable hostname needs a named tunnel + free Cloudflare account ([get started](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/)) — a later upgrade, not needed for the fixture test.

### 3. ngrok free
- $0, but requires an account + authtoken. Free plan: 1 auto-assigned dev domain (stable across restarts), up to 3 online endpoints, 20k HTTP req/mo, 1 GB egress/mo, 4k req/min, no timeout on free endpoints ([pricing](https://ngrok.com/pricing), [pricing & limits](https://ngrok.com/docs/pricing-limits), [free plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits/)).
- Friction for our fixture: every guest's first visit hits ngrok's anti-phishing **interstitial page** ("you are about to visit…", click Visit, 7-day cookie) on free-tier HTML traffic ([free plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits/)). No custom domains on free. 1 user only.
- Verdict: strictly worse than Quick Tunnel for a friends-and-phones test (account required + interstitial), kept as second tunnel option if Cloudflare is ever blocked.

### 4. Tailscale — surveyed, excluded
- The Personal plan is in fact `$0 free forever` (currently up to 6 users, unlimited user devices) and Funnel (public URL without guests installing anything) is available on all plans — the burned 7-day Premium trial does not kill the free tier ([pricing](https://tailscale.com/pricing), [Funnel docs](https://tailscale.com/docs/features/tailscale-funnel)). Serve shares tailnet-only (guests install Tailscale + join); Funnel shares publicly but needs MagicDNS + HTTPS certs + a `funnel` node attribute, ports 443/8443/10000, and macOS needs the standalone/open-source client variant for full function ([Funnel docs](https://tailscale.com/docs/features/tailscale-funnel)).
- Excluded anyway: user ground truth says treat Tailscale as unavailable/paid. Revisit only if that changes — it would then beat ngrok (no interstitial, identity-based access).

### 5. localhost + screen-share
- No URL at all: host runs the board on `localhost`, shares screen over FaceTime/Zoom/Meet. Zero setup, works on any network, zero attack surface — but guests can't interact; the facilitator drives. Last-resort fallback only.

## Recommendation (Justice fixture test)

- **Default: Cloudflare Quick Tunnel.** `cloudflared tunnel --url http://localhost:PORT`, QR-encode the printed `https://….trycloudflare.com` URL; two friends join from anywhere, no accounts anywhere in the loop. Concrete run: host serves the Justice board (Thrasymachus's "justice is the advantage of the stronger" as the opening claim node), friends open the QR URL on phones/laptops and add rebuttal nodes live. Caveats to carry into build: re-QR per session (rotating URL), no SSE (use WebSocket/polling), dev-only SLA is fine for a fixture test.
- **Fallback: LAN + QR.** If the tunnel is ever unreachable (or for a same-room session where you want zero third parties and minimum latency): serve on LAN, QR-encode `http://<lan-ip>:PORT`, friends join on the same Wi-Fi. If even the LAN fails (e.g. captive-portal Wi-Fi blocking device-to-device), drop to localhost + screen-share with the host driving.

## Sources
- Cloudflare Quick Tunnels: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
- Cloudflare Tunnel (outbound-only model): https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
- Cloudflare Tunnel get-started (named tunnels need account): https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/
- trycloudflare.com: https://trycloudflare.com/
- ngrok pricing (free tier): https://ngrok.com/pricing
- ngrok pricing & limits: https://ngrok.com/docs/pricing-limits
- ngrok free plan limits (quotas, dev domain, interstitial): https://ngrok.com/docs/pricing-limits/free-plan-limits/
- Tailscale pricing (Personal $0): https://tailscale.com/pricing
- Tailscale Funnel: https://tailscale.com/docs/features/tailscale-funnel
- Apple Bonjour: https://developer.apple.com/bonjour/
