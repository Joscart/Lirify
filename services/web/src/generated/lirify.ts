import type * as grpc from '@grpc/grpc-js';
import type { MessageTypeDefinition } from '@grpc/proto-loader';

import type { LirifyServiceClient as _lirify_v1_LirifyServiceClient, LirifyServiceDefinition as _lirify_v1_LirifyServiceDefinition } from './lirify/v1/LirifyService';

type SubtypeConstructor<Constructor extends new (...args: any) => any, Subtype> = {
  new(...args: ConstructorParameters<Constructor>): Subtype;
};

export interface ProtoGrpcType {
  lirify: {
    v1: {
      ExtractVideoIdsRequest: MessageTypeDefinition
      ExtractVideoIdsResponse: MessageTypeDefinition
      FailedSong: MessageTypeDefinition
      GetFailedSongsRequest: MessageTypeDefinition
      GetFailedSongsResponse: MessageTypeDefinition
      GetIndexStatsRequest: MessageTypeDefinition
      GetJobRequest: MessageTypeDefinition
      GetJobResponse: MessageTypeDefinition
      GetLyricsRequest: MessageTypeDefinition
      GetLyricsResponse: MessageTypeDefinition
      GetTrackRequest: MessageTypeDefinition
      GetTrackResponse: MessageTypeDefinition
      IndexPlaylistFromBotRequest: MessageTypeDefinition
      IndexPlaylistFromBotResponse: MessageTypeDefinition
      IndexPlaylistRequest: MessageTypeDefinition
      IndexStats: MessageTypeDefinition
      Job: MessageTypeDefinition
      LirifyService: SubtypeConstructor<typeof grpc.Client, _lirify_v1_LirifyServiceClient> & { service: _lirify_v1_LirifyServiceDefinition }
      ListTracksRequest: MessageTypeDefinition
      ListTracksResponse: MessageTypeDefinition
      LyricsLine: MessageTypeDefinition
      MatrixPreview: MessageTypeDefinition
      MatrixPreviewRequest: MessageTypeDefinition
      MatrixPreviewResponse: MessageTypeDefinition
      MatrixPreviewRow: MessageTypeDefinition
      QueuePlaylistsRequest: MessageTypeDefinition
      QueuePlaylistsResponse: MessageTypeDefinition
      RecommendRequest: MessageTypeDefinition
      RecommendResponse: MessageTypeDefinition
      RetryFailedRequest: MessageTypeDefinition
      RetryFailedResponse: MessageTypeDefinition
      SearchRequest: MessageTypeDefinition
      SearchResponse: MessageTypeDefinition
      StreamRequest: MessageTypeDefinition
      StreamResponse: MessageTypeDefinition
      Track: MessageTypeDefinition
      TrackSummary: MessageTypeDefinition
      WatchIndexStatsRequest: MessageTypeDefinition
    }
  }
}

