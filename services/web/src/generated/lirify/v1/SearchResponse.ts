// Original file: proto/lirify.proto

import type { TrackSummary as _lirify_v1_TrackSummary, TrackSummary__Output as _lirify_v1_TrackSummary__Output } from '../../lirify/v1/TrackSummary';

export interface SearchResponse {
  'query'?: (string);
  'results'?: (_lirify_v1_TrackSummary)[];
}

export interface SearchResponse__Output {
  'query': (string);
  'results': (_lirify_v1_TrackSummary__Output)[];
}
