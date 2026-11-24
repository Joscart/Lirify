// Original file: proto/lirify.proto

import type { Job as _lirify_v1_Job, Job__Output as _lirify_v1_Job__Output } from '../../lirify/v1/Job';
import type { Long } from '@grpc/proto-loader';

export interface IndexStats {
  'indexedSongs'?: (number);
  'videoIds'?: (number);
  'vocabularySize'?: (number);
  'invertedTerms'?: (number);
  'lyricsTokens'?: (number | string | Long);
  'languages'?: ({[key: string]: number});
  'backends'?: ({[key: string]: number});
  'playlistPending'?: (number);
  'matrixPending'?: (number);
  'failedSongs'?: (number);
  'cachedLyrics'?: (number);
  'jobs'?: (_lirify_v1_Job)[];
  'matricesAvailable'?: (string)[];
  'weights'?: ({[key: string]: number | string});
  'generatedAt'?: (number | string | Long);
  'lyricsProviders'?: (string)[];
  'topTerms'?: (string)[];
  'stateless'?: (boolean);
  'tracksStore'?: (string);
  'vectorsStore'?: (string);
  'maxIndexedSongs'?: (number);
  'serveOnly'?: (boolean);
  'mode'?: (string);
  'embeddingProvider'?: (string);
  'tokenizer'?: (string);
  'jaccardScope'?: (string);
  'localVocabularyTerms'?: (number);
  'localInvertedTerms'?: (number);
  'localIndexDir'?: (string);
}

export interface IndexStats__Output {
  'indexedSongs': (number);
  'videoIds': (number);
  'vocabularySize': (number);
  'invertedTerms': (number);
  'lyricsTokens': (string);
  'languages': ({[key: string]: number});
  'backends': ({[key: string]: number});
  'playlistPending': (number);
  'matrixPending': (number);
  'failedSongs': (number);
  'cachedLyrics': (number);
  'jobs': (_lirify_v1_Job__Output)[];
  'matricesAvailable': (string)[];
  'weights': ({[key: string]: number});
  'generatedAt': (string);
  'lyricsProviders': (string)[];
  'topTerms': (string)[];
  'stateless': (boolean);
  'tracksStore': (string);
  'vectorsStore': (string);
  'maxIndexedSongs': (number);
  'serveOnly': (boolean);
  'mode': (string);
  'embeddingProvider': (string);
  'tokenizer': (string);
  'jaccardScope': (string);
  'localVocabularyTerms': (number);
  'localInvertedTerms': (number);
  'localIndexDir': (string);
}
