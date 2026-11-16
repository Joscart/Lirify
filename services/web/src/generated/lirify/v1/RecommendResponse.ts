// Original file: proto/lirify.proto

import type { TrackSummary as _lirify_v1_TrackSummary, TrackSummary__Output as _lirify_v1_TrackSummary__Output } from '../../lirify/v1/TrackSummary';

export interface RecommendResponse {
  'seedVideoId'?: (string);
  'recommendations'?: (_lirify_v1_TrackSummary)[];
  'engine'?: (string);
}

export interface RecommendResponse__Output {
  'seedVideoId': (string);
  'recommendations': (_lirify_v1_TrackSummary__Output)[];
  'engine': (string);
}
