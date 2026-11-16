// Original file: proto/lirify.proto

import type { Job as _lirify_v1_Job, Job__Output as _lirify_v1_Job__Output } from '../../lirify/v1/Job';

export interface QueuePlaylistsResponse {
  'jobs'?: (_lirify_v1_Job)[];
  'queueSize'?: (number);
}

export interface QueuePlaylistsResponse__Output {
  'jobs': (_lirify_v1_Job__Output)[];
  'queueSize': (number);
}
