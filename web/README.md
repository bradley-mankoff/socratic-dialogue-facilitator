# Web forum home.

`web/forum.py` is the forum's stdlib server, called Symposia on screen:
a landing page splitting into Start a Symposium (the start screen: host
name and email, then a Settings box with the Symposium's name, the word
and an Anonymous Mode toggle, off by default) and Continue a Symposium
(a placeholder until Bead sdf-zj6.15 fills it). Pressing Start opens the
Symposium at once on the players page, headed by the Symposium's name,
where "Add a player" adds one row reading "Invited" with a note field
and a Share button carrying one message (the note, then the player's
link). Guests open personal invitation links and name themselves on
arrival.
`python -m web.forum` serves the repo-local `store/` data home
with the live dictionary chain. Symposium records (name, word, Anonymous
Mode, players, tokens, the host's notes to each invitee, who has joined)
live in `store/symposiums.json` beside the registry; the
verdict state underneath stays a board, and no page ever shows that word.
No page shows anyone's email but the host's own on the host's own players
page, and no page says room. Personal links are absolute (built
from the request Host header, so they paste into Messages or Mail as
something a guest can open) until sdf-mgt.22 supplies the fixed
Tailscale address; Start signs the host's browser in with a persistent
cookie. With Anonymous Mode on no page shows any name; random animals
arrive in sdf-zj6.3.
