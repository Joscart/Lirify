// Original file: proto/lirify.proto

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
  'errorCode'?: (string);
  'retryMode'?: (string);
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
  'errorCode': (string);
  'retryMode': (string);
}
