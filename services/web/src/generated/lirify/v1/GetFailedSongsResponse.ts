// Original file: proto/lirify.proto

import type { FailedSong as _lirify_v1_FailedSong, FailedSong__Output as _lirify_v1_FailedSong__Output } from '../../lirify/v1/FailedSong';

export interface GetFailedSongsResponse {
  'total'?: (number);
  'cachedLyrics'?: (number);
  'maxAttempts'?: (number);
  'retryIntervalSeconds'?: (number);
  'failed'?: (_lirify_v1_FailedSong)[];
}

export interface GetFailedSongsResponse__Output {
  'total': (number);
  'cachedLyrics': (number);
  'maxAttempts': (number);
  'retryIntervalSeconds': (number);
  'failed': (_lirify_v1_FailedSong__Output)[];
}
