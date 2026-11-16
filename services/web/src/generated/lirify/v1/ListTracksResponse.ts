// Original file: proto/lirify.proto

import type { Track as _lirify_v1_Track, Track__Output as _lirify_v1_Track__Output } from '../../lirify/v1/Track';

export interface ListTracksResponse {
  'total'?: (number);
  'tracks'?: (_lirify_v1_Track)[];
}

export interface ListTracksResponse__Output {
  'total': (number);
  'tracks': (_lirify_v1_Track__Output)[];
}
