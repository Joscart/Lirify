// Original file: proto/lirify.proto

import type { Long } from '@grpc/proto-loader';

export interface StreamResponse {
  'videoId'?: (string);
  'url'?: (string);
  'duration'?: (number | string);
  'expiresAt'?: (number | string | Long);
}

export interface StreamResponse__Output {
  'videoId': (string);
  'url': (string);
  'duration': (number);
  'expiresAt': (string);
}
