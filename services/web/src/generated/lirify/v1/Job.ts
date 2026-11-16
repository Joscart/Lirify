// Original file: /home/joscart/Work/Lirify/proto/lirify.proto

import type { Long } from '@grpc/proto-loader';

export interface Job {
  'jobId'?: (string);
  'action'?: (string);
  'url'?: (string);
  'status'?: (string);
  'stage'?: (string);
  'error'?: (string);
  'added'?: (number);
  'attempts'?: (number);
  'source'?: (string);
  'createdAt'?: (number | string | Long);
  'updatedAt'?: (number | string | Long);
}

export interface Job__Output {
  'jobId': (string);
  'action': (string);
  'url': (string);
  'status': (string);
  'stage': (string);
  'error': (string);
  'added': (number);
  'attempts': (number);
  'source': (string);
  'createdAt': (string);
  'updatedAt': (string);
}
