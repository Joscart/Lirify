// Original file: proto/lirify.proto

import type { Long } from '@grpc/proto-loader';

export interface LyricsLine {
  'timeMs'?: (number | string | Long);
  'text'?: (string);
}

export interface LyricsLine__Output {
  'timeMs': (string);
  'text': (string);
}
