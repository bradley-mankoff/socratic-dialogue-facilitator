# Web forum home.

`web/forum.py` is the forum's stdlib server, called Symposia on screen:
a landing page splitting into Start a Symposium (the start screen: host
name and email, then a Settings box with the Symposium's name, the word
and an Anonymous Mode toggle, off by default) and Continue a Symposium
(a placeholder until Bead sdf-zj6.15 fills it). Pressing Start opens the
Symposium at once on the players page, headed by the Symposium's name,
where "Add a player" adds one row reading "Invited" with a note field
and a Share button carrying one message (the note, then the player's
link). With Anonymous Mode off, the first visit asks for a name, an
email and a player color, then shows the one instructions screen (the
Symposium's name, who else joined, how it works, Go In); the host picks
their own color the same way on entering, and a later visit goes
straight in. With Anonymous Mode on, the first visit asks only for an
email and deals a random animal (its icon with its name beside it, no
two alike, no name and no color; the host gets one the same way at
Start), then shows the same instructions screen; every page shows each
participant through the one rendering function, and the Symposium page
carries a small Who Is Here panel listing everyone and whether each has
joined. Joining is one-time: submitting the form again never
renames anyone nor deals a second animal.
`python -m web.forum` serves the repo-local `store/` data home
with the live dictionary chain. Symposium records (name, word, Anonymous
Mode, players, tokens, the host's notes to each invitee, who has joined
and entered, and each joined participant's name, email and player
color) live in `store/symposiums.json` beside the registry; the
verdict state underneath stays a board, and no page ever shows that word.
No page shows anyone's email but the host's own on the host's own players
page, and no page says room. Personal links are absolute (built
from the request Host header, so they paste into Messages or Mail as
something a guest can open) until sdf-mgt.22 supplies the fixed
Tailscale address; Start signs the host's browser in with a persistent
cookie. With Anonymous Mode on no page shows any name: everyone appears
as their random animal.
