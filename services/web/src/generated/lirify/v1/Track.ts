// Original file: proto/lirify.proto


export interface Track {
  'videoId'?: (string);
  'title'?: (string);
  'artist'?: (string);
  'language'?: (string);
  'backend'?: (string);
  'youtubeTitle'?: (string);
  'duration'?: (number | string);
  'lyrics'?: (string);
  'synced'?: (boolean);
  'thumb'?: (string);
  'streamUrl'?: (string);
}

export interface Track__Output {
  'videoId': (string);
  'title': (string);
  'artist': (string);
  'language': (string);
  'backend': (string);
  'youtubeTitle': (string);
  'duration': (number);
  'lyrics': (string);
  'synced': (boolean);
  'thumb': (string);
  'streamUrl': (string);
}
