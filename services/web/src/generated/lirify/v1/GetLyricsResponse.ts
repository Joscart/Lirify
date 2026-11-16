// Original file: proto/lirify.proto

import type { LyricsLine as _lirify_v1_LyricsLine, LyricsLine__Output as _lirify_v1_LyricsLine__Output } from '../../lirify/v1/LyricsLine';

export interface GetLyricsResponse {
  'videoId'?: (string);
  'synced'?: (boolean);
  'lines'?: (_lirify_v1_LyricsLine)[];
  'raw'?: (string);
  'language'?: (string);
}

export interface GetLyricsResponse__Output {
  'videoId': (string);
  'synced': (boolean);
  'lines': (_lirify_v1_LyricsLine__Output)[];
  'raw': (string);
  'language': (string);
}
