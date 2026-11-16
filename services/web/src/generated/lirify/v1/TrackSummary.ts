// Original file: proto/lirify.proto


export interface TrackSummary {
  'videoId'?: (string);
  'title'?: (string);
  'artist'?: (string);
  'language'?: (string);
  'score'?: (number | string);
  'thumb'?: (string);
  'duration'?: (number | string);
}

export interface TrackSummary__Output {
  'videoId': (string);
  'title': (string);
  'artist': (string);
  'language': (string);
  'score': (number);
  'thumb': (string);
  'duration': (number);
}
