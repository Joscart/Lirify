// Original file: proto/lirify.proto

import type { Long } from '@grpc/proto-loader';

export interface PublishToCloudResponse {
  'published'?: (boolean);
  'songs'?: (number);
  'vectors'?: (number);
  'vocabularyTerms'?: (number);
  'invertedTerms'?: (number);
  'directory'?: (string);
  'message'?: (string);
  'publishedAt'?: (number | string | Long);
  'unchanged'?: (boolean);
}

export interface PublishToCloudResponse__Output {
  'published': (boolean);
  'songs': (number);
  'vectors': (number);
  'vocabularyTerms': (number);
  'invertedTerms': (number);
  'directory': (string);
  'message': (string);
  'publishedAt': (string);
  'unchanged': (boolean);
}
