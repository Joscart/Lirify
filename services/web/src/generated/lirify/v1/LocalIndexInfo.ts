// Original file: proto/lirify.proto

import type { Long } from '@grpc/proto-loader';

export interface LocalIndexInfo {
  'directory'?: (string);
  'tokenizer'?: (string);
  'tokenizerBackend'?: (string);
  'embeddingProvider'?: (string);
  'documents'?: (number);
  'vocabularyTerms'?: (number);
  'invertedTerms'?: (number);
  'vocabularyBytes'?: (number | string | Long);
  'invertedIndexBytes'?: (number | string | Long);
  'updatedAt'?: (number | string | Long);
  'vocabularyPath'?: (string);
  'invertedIndexPath'?: (string);
}

export interface LocalIndexInfo__Output {
  'directory': (string);
  'tokenizer': (string);
  'tokenizerBackend': (string);
  'embeddingProvider': (string);
  'documents': (number);
  'vocabularyTerms': (number);
  'invertedTerms': (number);
  'vocabularyBytes': (string);
  'invertedIndexBytes': (string);
  'updatedAt': (string);
  'vocabularyPath': (string);
  'invertedIndexPath': (string);
}
