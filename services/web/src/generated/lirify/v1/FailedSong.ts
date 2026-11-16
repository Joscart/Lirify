// Original file: proto/lirify.proto

import type { Long } from '@grpc/proto-loader';

export interface FailedSong {
  'videoId'?: (string);
  'title'?: (string);
  'artist'?: (string);
  'reason'?: (string);
  'attempts'?: (number);
  'lastTry'?: (number | string | Long);
  'duration'?: (number | string);
}

export interface FailedSong__Output {
  'videoId': (string);
  'title': (string);
  'artist': (string);
  'reason': (string);
  'attempts': (number);
  'lastTry': (string);
  'duration': (number);
}
