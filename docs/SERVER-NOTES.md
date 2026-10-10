# Server-side notes

Issues found in the upstream server that are **documented, not patched** here.
The macOS port overlay in `server/` only carries macOS-compatibility changes;
game-logic fixes belong upstream.

## Character creation with race 21 (HiberniaMinotaur) fails

Creating a character with race 21 (HiberniaMinotaur) makes the server throw:

```
KeyNotFoundException: 'HiberniaMinotaur'
    at CharacterStatValidator.cs:33
```

(Observed 13:18:40 in `daoc-server-macos/dist/daoc-server/logs/console.out`.)

The client offers the race combination, but the server's stat validator has no
entry for minotaur races. Workaround: pick a classic race (Celt, Firbolg, Sylvan,
etc. for Hibernia). A proper fix would add the minotaur entries to the upstream
validator — that change belongs in the upstream repo, not in this packaging repo.