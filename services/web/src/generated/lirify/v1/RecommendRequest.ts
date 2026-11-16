// Original file: proto/lirify.proto


export interface RecommendRequest {
  'videoId'?: (string);
  'limit'?: (number);
  'seedVideoIds'?: (string)[];
}

export interface RecommendRequest__Output {
  'videoId': (string);
  'limit': (number);
  'seedVideoIds': (string)[];
}
