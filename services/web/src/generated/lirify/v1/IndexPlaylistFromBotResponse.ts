// Original file: /home/joscart/Work/Lirify/proto/lirify.proto

import type { Job as _lirify_v1_Job, Job__Output as _lirify_v1_Job__Output } from '../../lirify/v1/Job';

export interface IndexPlaylistFromBotResponse {
  'accepted'?: (boolean);
  'job'?: (_lirify_v1_Job | null);
  'jobStatusUrl'?: (string);
}

export interface IndexPlaylistFromBotResponse__Output {
  'accepted': (boolean);
  'job': (_lirify_v1_Job__Output | null);
  'jobStatusUrl': (string);
}
