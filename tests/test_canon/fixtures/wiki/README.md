# Wiki fixtures — attribution

These two files are saved responses from the **Forgotten Realms Wiki**
MediaWiki API (`https://forgottenrealms.fandom.com/api.php`), captured so the
gazetteer parser can be tested without network access.

| file | source page(s) |
|---|---|
| `index-parse.json` | [`Curse of Strahd`](https://forgottenrealms.fandom.com/wiki/Curse_of_Strahd) — the `==Index==` section |
| `pages-batch.json` | a 50-title batch of the entity pages that index links to |

## Licence

Forgotten Realms Wiki content is licensed **CC BY-SA 3.0**
(<https://creativecommons.org/licenses/by-sa/3.0/>), as stated at
<https://forgottenrealms.fandom.com/wiki/Forgotten_Realms_Wiki:Copyrights>.

The wikitext in these files is reproduced under that licence. It is
attributed here to the Forgotten Realms Wiki and its contributors, and it
remains under CC BY-SA — the share-alike term applies to this text, not to
the rest of this repository, which is separately licensed.

Content was retrieved via the public API, unmodified apart from being stored
as the API returned it. Page histories and contributor lists are available at
the URLs above.

## Not included

The harvested gazetteer itself (`data/gazetteer/`) is **not** committed — it
is gitignored, as is the D&D Beyond corpus. Only these two small parser
fixtures are in the repository.
