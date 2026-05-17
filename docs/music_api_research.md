# Music API Research

Date: 2026-04-17

This is an archived research note. It records earlier local experiments and
should not be treated as a guarantee that any external API still behaves the
same way.

Provider matching and popularity data are not part of the current runtime model.
The current schema deliberately keeps music-provider data deferred so the core
timeline can stabilize first.

## Goal

Explore ways to enrich `music_tracks` with public music-platform metadata such
as:

- provider ids
- popularity scores
- listener or play counts
- comment counts

The important modeling point is that this data belongs to real music tracks,
not to one specific WannaDance entry. A single song can have multiple dance
versions.

## Candidates

### NetEase Cloud Music

Earlier local tests found that NetEase endpoints were reachable without local
API keys and could return:

- search results
- song detail fields such as `popularity`
- comment counts

Observed endpoints during testing:

```text
https://music.163.com/api/search/get?s={query}&type=1&limit=3
https://music.163.com/api/song/detail?ids=[{id}]
https://music.163.com/api/v1/resource/comments/R_SO_4_{id}?limit=1
```

Requests used a browser-like `User-Agent` and `Referer`.

Risks:

- unofficial endpoint
- matching can confuse covers, remixes, live versions, and translations
- availability and response shape may change

### Last.fm

Last.fm has an official API and can expose global statistics such as:

- play count
- listener count

Risks:

- requires an API key
- matching quality depends on title/artist normalization
- coverage may vary for Chinese, remix, or dance-version metadata

### Spotify

Spotify Web API exposes a 0-100 popularity score.

Risks:

- requires OAuth credentials
- public API does not expose precise total play counts
- regional availability and canonical-track matching can be tricky

### YouTube Data API

YouTube can provide video-level statistics when a specific video is known.

Risks:

- requires an API key
- tracks may map to many videos rather than one canonical song
- quota limits matter

### Deezer

Earlier local tests were limited by regional availability.

## Existing Research Scripts

- `scripts/test_music_apis.py`: ad hoc API probes.
- `scripts/match_netease.py`: experimental NetEase matching and comment-count
  lookup.

These scripts are research tools, not runtime commands.

## Suggested Future Schema

Provider identifiers should be stored separately from the core timeline:

```text
music_tracks
  -> music_provider_matches
  -> music_popularity_snapshots
```

Possible future tables:

- `music_provider_matches`: maps `music_tracks.id` to provider ids, with
  confidence and match method.
- `music_popularity_snapshots`: stores time-stamped provider metrics such as
  popularity, comments, listeners, or play counts.

This keeps changing provider data away from immutable playback history.

## Recommendation

Do not include provider popularity in the recommendation score yet.

The next useful step is a manual-reviewable provider matching workflow:

1. Take a batch of `music_tracks`.
2. Search provider candidates by normalized title and artist.
3. Store candidate matches with confidence and provider payload.
4. Allow manual correction before using matches in analytics or recommendations.
