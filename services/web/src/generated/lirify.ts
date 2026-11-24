import type * as grpc from '@grpc/grpc-js';
import type { MessageTypeDefinition } from '@grpc/proto-loader';

import type { LirifyIndexerServiceClient as _lirify_v1_LirifyIndexerServiceClient, LirifyIndexerServiceDefinition as _lirify_v1_LirifyIndexerServiceDefinition } from './lirify/v1/LirifyIndexerService';
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
      GetLocalIndexRequest: MessageTypeDefinition
      GetLocalIndexResponse: MessageTypeDefinition
      GetLyricsRequest: MessageTypeDefinition
      GetLyricsResponse: MessageTypeDefinition
      GetTrackRequest: MessageTypeDefinition
      GetTrackResponse: MessageTypeDefinition
      IndexPlaylistFromBotRequest: MessageTypeDefinition
      IndexPlaylistFromBotResponse: MessageTypeDefinition
      IndexPlaylistRequest: MessageTypeDefinition
      IndexStats: MessageTypeDefinition
      Job: MessageTypeDefinition
      LirifyIndexerService: SubtypeConstructor<typeof grpc.Client, _lirify_v1_LirifyIndexerServiceClient> & { service: _lirify_v1_LirifyIndexerServiceDefinition }
      LirifyService: SubtypeConstructor<typeof grpc.Client, _lirify_v1_LirifyServiceClient> & { service: _lirify_v1_LirifyServiceDefinition }
      ListTracksRequest: MessageTypeDefinition
      ListTracksResponse: MessageTypeDefinition
      LocalIndexInfo: MessageTypeDefinition
      LyricsLine: MessageTypeDefinition
      MatrixPreview: MessageTypeDefinition
      MatrixPreviewRequest: MessageTypeDefinition
      MatrixPreviewResponse: MessageTypeDefinition
      MatrixPreviewRow: MessageTypeDefinition
      PublishToCloudRequest: MessageTypeDefinition
      PublishToCloudResponse: MessageTypeDefinition
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

