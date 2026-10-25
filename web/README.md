# Web forum home.

`web/forum.py` is the forum's stdlib server: start a Symposium with its
people, open personal invitation links, and pick or write its first
definition. `python -m web.forum` serves the repo-local `store/` data home
with the live dictionary chain. Symposium records (word, people, tokens,
who has joined) live in `store/symposiums.json` beside the registry; the
verdict state underneath stays a board, and no page ever shows that word.
