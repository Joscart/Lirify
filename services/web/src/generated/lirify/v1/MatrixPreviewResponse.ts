// Original file: /home/joscart/Work/Lirify/proto/lirify.proto

import type { TrackSummary as _lirify_v1_TrackSummary, TrackSummary__Output as _lirify_v1_TrackSummary__Output } from '../../lirify/v1/TrackSummary';
import type { MatrixPreview as _lirify_v1_MatrixPreview, MatrixPreview__Output as _lirify_v1_MatrixPreview__Output } from '../../lirify/v1/MatrixPreview';

export interface MatrixPreviewResponse {
  'shape'?: (number)[];
  'size'?: (number);
  'songs'?: (_lirify_v1_TrackSummary)[];
  'matrices'?: ({[key: string]: _lirify_v1_MatrixPreview});
  'weights'?: ({[key: string]: number | string});
}

export interface MatrixPreviewResponse__Output {
  'shape': (number)[];
  'size': (number);
  'songs': (_lirify_v1_TrackSummary__Output)[];
  'matrices': ({[key: string]: _lirify_v1_MatrixPreview__Output});
  'weights': ({[key: string]: number});
}
