// Original file: proto/lirify.proto

import type * as grpc from '@grpc/grpc-js'
import type { MethodDefinition } from '@grpc/proto-loader'
import type { ExtractVideoIdsRequest as _lirify_v1_ExtractVideoIdsRequest, ExtractVideoIdsRequest__Output as _lirify_v1_ExtractVideoIdsRequest__Output } from '../../lirify/v1/ExtractVideoIdsRequest';
import type { ExtractVideoIdsResponse as _lirify_v1_ExtractVideoIdsResponse, ExtractVideoIdsResponse__Output as _lirify_v1_ExtractVideoIdsResponse__Output } from '../../lirify/v1/ExtractVideoIdsResponse';
import type { GetFailedSongsRequest as _lirify_v1_GetFailedSongsRequest, GetFailedSongsRequest__Output as _lirify_v1_GetFailedSongsRequest__Output } from '../../lirify/v1/GetFailedSongsRequest';
import type { GetFailedSongsResponse as _lirify_v1_GetFailedSongsResponse, GetFailedSongsResponse__Output as _lirify_v1_GetFailedSongsResponse__Output } from '../../lirify/v1/GetFailedSongsResponse';
import type { GetIndexStatsRequest as _lirify_v1_GetIndexStatsRequest, GetIndexStatsRequest__Output as _lirify_v1_GetIndexStatsRequest__Output } from '../../lirify/v1/GetIndexStatsRequest';
import type { GetJobRequest as _lirify_v1_GetJobRequest, GetJobRequest__Output as _lirify_v1_GetJobRequest__Output } from '../../lirify/v1/GetJobRequest';
import type { GetJobResponse as _lirify_v1_GetJobResponse, GetJobResponse__Output as _lirify_v1_GetJobResponse__Output } from '../../lirify/v1/GetJobResponse';
import type { GetLyricsRequest as _lirify_v1_GetLyricsRequest, GetLyricsRequest__Output as _lirify_v1_GetLyricsRequest__Output } from '../../lirify/v1/GetLyricsRequest';
import type { GetLyricsResponse as _lirify_v1_GetLyricsResponse, GetLyricsResponse__Output as _lirify_v1_GetLyricsResponse__Output } from '../../lirify/v1/GetLyricsResponse';
import type { GetTrackRequest as _lirify_v1_GetTrackRequest, GetTrackRequest__Output as _lirify_v1_GetTrackRequest__Output } from '../../lirify/v1/GetTrackRequest';
import type { GetTrackResponse as _lirify_v1_GetTrackResponse, GetTrackResponse__Output as _lirify_v1_GetTrackResponse__Output } from '../../lirify/v1/GetTrackResponse';
import type { IndexPlaylistFromBotRequest as _lirify_v1_IndexPlaylistFromBotRequest, IndexPlaylistFromBotRequest__Output as _lirify_v1_IndexPlaylistFromBotRequest__Output } from '../../lirify/v1/IndexPlaylistFromBotRequest';
import type { IndexPlaylistFromBotResponse as _lirify_v1_IndexPlaylistFromBotResponse, IndexPlaylistFromBotResponse__Output as _lirify_v1_IndexPlaylistFromBotResponse__Output } from '../../lirify/v1/IndexPlaylistFromBotResponse';
import type { IndexPlaylistRequest as _lirify_v1_IndexPlaylistRequest, IndexPlaylistRequest__Output as _lirify_v1_IndexPlaylistRequest__Output } from '../../lirify/v1/IndexPlaylistRequest';
import type { IndexStats as _lirify_v1_IndexStats, IndexStats__Output as _lirify_v1_IndexStats__Output } from '../../lirify/v1/IndexStats';
import type { Job as _lirify_v1_Job, Job__Output as _lirify_v1_Job__Output } from '../../lirify/v1/Job';
import type { ListTracksRequest as _lirify_v1_ListTracksRequest, ListTracksRequest__Output as _lirify_v1_ListTracksRequest__Output } from '../../lirify/v1/ListTracksRequest';
import type { ListTracksResponse as _lirify_v1_ListTracksResponse, ListTracksResponse__Output as _lirify_v1_ListTracksResponse__Output } from '../../lirify/v1/ListTracksResponse';
import type { MatrixPreviewRequest as _lirify_v1_MatrixPreviewRequest, MatrixPreviewRequest__Output as _lirify_v1_MatrixPreviewRequest__Output } from '../../lirify/v1/MatrixPreviewRequest';
import type { MatrixPreviewResponse as _lirify_v1_MatrixPreviewResponse, MatrixPreviewResponse__Output as _lirify_v1_MatrixPreviewResponse__Output } from '../../lirify/v1/MatrixPreviewResponse';
import type { QueuePlaylistsRequest as _lirify_v1_QueuePlaylistsRequest, QueuePlaylistsRequest__Output as _lirify_v1_QueuePlaylistsRequest__Output } from '../../lirify/v1/QueuePlaylistsRequest';
import type { QueuePlaylistsResponse as _lirify_v1_QueuePlaylistsResponse, QueuePlaylistsResponse__Output as _lirify_v1_QueuePlaylistsResponse__Output } from '../../lirify/v1/QueuePlaylistsResponse';
import type { RecommendRequest as _lirify_v1_RecommendRequest, RecommendRequest__Output as _lirify_v1_RecommendRequest__Output } from '../../lirify/v1/RecommendRequest';
import type { RecommendResponse as _lirify_v1_RecommendResponse, RecommendResponse__Output as _lirify_v1_RecommendResponse__Output } from '../../lirify/v1/RecommendResponse';
import type { RetryFailedRequest as _lirify_v1_RetryFailedRequest, RetryFailedRequest__Output as _lirify_v1_RetryFailedRequest__Output } from '../../lirify/v1/RetryFailedRequest';
import type { RetryFailedResponse as _lirify_v1_RetryFailedResponse, RetryFailedResponse__Output as _lirify_v1_RetryFailedResponse__Output } from '../../lirify/v1/RetryFailedResponse';
import type { SearchRequest as _lirify_v1_SearchRequest, SearchRequest__Output as _lirify_v1_SearchRequest__Output } from '../../lirify/v1/SearchRequest';
import type { SearchResponse as _lirify_v1_SearchResponse, SearchResponse__Output as _lirify_v1_SearchResponse__Output } from '../../lirify/v1/SearchResponse';
import type { StreamRequest as _lirify_v1_StreamRequest, StreamRequest__Output as _lirify_v1_StreamRequest__Output } from '../../lirify/v1/StreamRequest';
import type { StreamResponse as _lirify_v1_StreamResponse, StreamResponse__Output as _lirify_v1_StreamResponse__Output } from '../../lirify/v1/StreamResponse';
import type { WatchIndexStatsRequest as _lirify_v1_WatchIndexStatsRequest, WatchIndexStatsRequest__Output as _lirify_v1_WatchIndexStatsRequest__Output } from '../../lirify/v1/WatchIndexStatsRequest';

export interface LirifyServiceClient extends grpc.Client {
  ExtractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  ExtractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  ExtractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  ExtractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  extractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  extractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  extractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  extractVideoIds(argument: _lirify_v1_ExtractVideoIdsRequest, callback: grpc.requestCallback<_lirify_v1_ExtractVideoIdsResponse__Output>): grpc.ClientUnaryCall;
  
  GetFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  GetFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  GetFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  GetFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  getFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  getFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  getFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  getFailedSongs(argument: _lirify_v1_GetFailedSongsRequest, callback: grpc.requestCallback<_lirify_v1_GetFailedSongsResponse__Output>): grpc.ClientUnaryCall;
  
  GetIndexStats(argument: _lirify_v1_GetIndexStatsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  GetIndexStats(argument: _lirify_v1_GetIndexStatsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  GetIndexStats(argument: _lirify_v1_GetIndexStatsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  GetIndexStats(argument: _lirify_v1_GetIndexStatsRequest, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  getIndexStats(argument: _lirify_v1_GetIndexStatsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  getIndexStats(argument: _lirify_v1_GetIndexStatsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  getIndexStats(argument: _lirify_v1_GetIndexStatsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  getIndexStats(argument: _lirify_v1_GetIndexStatsRequest, callback: grpc.requestCallback<_lirify_v1_IndexStats__Output>): grpc.ClientUnaryCall;
  
  GetJob(argument: _lirify_v1_GetJobRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  GetJob(argument: _lirify_v1_GetJobRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  GetJob(argument: _lirify_v1_GetJobRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  GetJob(argument: _lirify_v1_GetJobRequest, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  getJob(argument: _lirify_v1_GetJobRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  getJob(argument: _lirify_v1_GetJobRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  getJob(argument: _lirify_v1_GetJobRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  getJob(argument: _lirify_v1_GetJobRequest, callback: grpc.requestCallback<_lirify_v1_GetJobResponse__Output>): grpc.ClientUnaryCall;
  
  GetLyrics(argument: _lirify_v1_GetLyricsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  GetLyrics(argument: _lirify_v1_GetLyricsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  GetLyrics(argument: _lirify_v1_GetLyricsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  GetLyrics(argument: _lirify_v1_GetLyricsRequest, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  getLyrics(argument: _lirify_v1_GetLyricsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  getLyrics(argument: _lirify_v1_GetLyricsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  getLyrics(argument: _lirify_v1_GetLyricsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  getLyrics(argument: _lirify_v1_GetLyricsRequest, callback: grpc.requestCallback<_lirify_v1_GetLyricsResponse__Output>): grpc.ClientUnaryCall;
  
  GetTrack(argument: _lirify_v1_GetTrackRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  GetTrack(argument: _lirify_v1_GetTrackRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  GetTrack(argument: _lirify_v1_GetTrackRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  GetTrack(argument: _lirify_v1_GetTrackRequest, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  getTrack(argument: _lirify_v1_GetTrackRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  getTrack(argument: _lirify_v1_GetTrackRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  getTrack(argument: _lirify_v1_GetTrackRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  getTrack(argument: _lirify_v1_GetTrackRequest, callback: grpc.requestCallback<_lirify_v1_GetTrackResponse__Output>): grpc.ClientUnaryCall;
  
  IndexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  IndexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  IndexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  IndexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  indexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  indexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  indexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  indexPlaylist(argument: _lirify_v1_IndexPlaylistRequest, callback: grpc.requestCallback<_lirify_v1_Job__Output>): grpc.ClientUnaryCall;
  
  IndexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  IndexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  IndexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  IndexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  indexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  indexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  indexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  indexPlaylistFromBot(argument: _lirify_v1_IndexPlaylistFromBotRequest, callback: grpc.requestCallback<_lirify_v1_IndexPlaylistFromBotResponse__Output>): grpc.ClientUnaryCall;
  
  ListTracks(argument: _lirify_v1_ListTracksRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  ListTracks(argument: _lirify_v1_ListTracksRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  ListTracks(argument: _lirify_v1_ListTracksRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  ListTracks(argument: _lirify_v1_ListTracksRequest, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  listTracks(argument: _lirify_v1_ListTracksRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  listTracks(argument: _lirify_v1_ListTracksRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  listTracks(argument: _lirify_v1_ListTracksRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  listTracks(argument: _lirify_v1_ListTracksRequest, callback: grpc.requestCallback<_lirify_v1_ListTracksResponse__Output>): grpc.ClientUnaryCall;
  
  MatrixPreview(argument: _lirify_v1_MatrixPreviewRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  MatrixPreview(argument: _lirify_v1_MatrixPreviewRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  MatrixPreview(argument: _lirify_v1_MatrixPreviewRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  MatrixPreview(argument: _lirify_v1_MatrixPreviewRequest, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  matrixPreview(argument: _lirify_v1_MatrixPreviewRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  matrixPreview(argument: _lirify_v1_MatrixPreviewRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  matrixPreview(argument: _lirify_v1_MatrixPreviewRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  matrixPreview(argument: _lirify_v1_MatrixPreviewRequest, callback: grpc.requestCallback<_lirify_v1_MatrixPreviewResponse__Output>): grpc.ClientUnaryCall;
  
  QueuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  QueuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  QueuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  QueuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  queuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  queuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  queuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  queuePlaylists(argument: _lirify_v1_QueuePlaylistsRequest, callback: grpc.requestCallback<_lirify_v1_QueuePlaylistsResponse__Output>): grpc.ClientUnaryCall;
  
  Recommend(argument: _lirify_v1_RecommendRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  Recommend(argument: _lirify_v1_RecommendRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  Recommend(argument: _lirify_v1_RecommendRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  Recommend(argument: _lirify_v1_RecommendRequest, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  recommend(argument: _lirify_v1_RecommendRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  recommend(argument: _lirify_v1_RecommendRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  recommend(argument: _lirify_v1_RecommendRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  recommend(argument: _lirify_v1_RecommendRequest, callback: grpc.requestCallback<_lirify_v1_RecommendResponse__Output>): grpc.ClientUnaryCall;
  
  RetryFailed(argument: _lirify_v1_RetryFailedRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  RetryFailed(argument: _lirify_v1_RetryFailedRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  RetryFailed(argument: _lirify_v1_RetryFailedRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  RetryFailed(argument: _lirify_v1_RetryFailedRequest, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  retryFailed(argument: _lirify_v1_RetryFailedRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  retryFailed(argument: _lirify_v1_RetryFailedRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  retryFailed(argument: _lirify_v1_RetryFailedRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  retryFailed(argument: _lirify_v1_RetryFailedRequest, callback: grpc.requestCallback<_lirify_v1_RetryFailedResponse__Output>): grpc.ClientUnaryCall;
  
  Search(argument: _lirify_v1_SearchRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  Search(argument: _lirify_v1_SearchRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  Search(argument: _lirify_v1_SearchRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  Search(argument: _lirify_v1_SearchRequest, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  search(argument: _lirify_v1_SearchRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  search(argument: _lirify_v1_SearchRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  search(argument: _lirify_v1_SearchRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  search(argument: _lirify_v1_SearchRequest, callback: grpc.requestCallback<_lirify_v1_SearchResponse__Output>): grpc.ClientUnaryCall;
  
  Stream(argument: _lirify_v1_StreamRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  Stream(argument: _lirify_v1_StreamRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  Stream(argument: _lirify_v1_StreamRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  Stream(argument: _lirify_v1_StreamRequest, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  stream(argument: _lirify_v1_StreamRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  stream(argument: _lirify_v1_StreamRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  stream(argument: _lirify_v1_StreamRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  stream(argument: _lirify_v1_StreamRequest, callback: grpc.requestCallback<_lirify_v1_StreamResponse__Output>): grpc.ClientUnaryCall;
  
  WatchIndexStats(argument: _lirify_v1_WatchIndexStatsRequest, metadata: grpc.Metadata, options?: grpc.CallOptions): grpc.ClientReadableStream<_lirify_v1_IndexStats__Output>;
  WatchIndexStats(argument: _lirify_v1_WatchIndexStatsRequest, options?: grpc.CallOptions): grpc.ClientReadableStream<_lirify_v1_IndexStats__Output>;
  watchIndexStats(argument: _lirify_v1_WatchIndexStatsRequest, metadata: grpc.Metadata, options?: grpc.CallOptions): grpc.ClientReadableStream<_lirify_v1_IndexStats__Output>;
  watchIndexStats(argument: _lirify_v1_WatchIndexStatsRequest, options?: grpc.CallOptions): grpc.ClientReadableStream<_lirify_v1_IndexStats__Output>;
  
}

export interface LirifyServiceHandlers extends grpc.UntypedServiceImplementation {
  ExtractVideoIds: grpc.handleUnaryCall<_lirify_v1_ExtractVideoIdsRequest__Output, _lirify_v1_ExtractVideoIdsResponse>;
  
  GetFailedSongs: grpc.handleUnaryCall<_lirify_v1_GetFailedSongsRequest__Output, _lirify_v1_GetFailedSongsResponse>;
  
  GetIndexStats: grpc.handleUnaryCall<_lirify_v1_GetIndexStatsRequest__Output, _lirify_v1_IndexStats>;
  
  GetJob: grpc.handleUnaryCall<_lirify_v1_GetJobRequest__Output, _lirify_v1_GetJobResponse>;
  
  GetLyrics: grpc.handleUnaryCall<_lirify_v1_GetLyricsRequest__Output, _lirify_v1_GetLyricsResponse>;
  
  GetTrack: grpc.handleUnaryCall<_lirify_v1_GetTrackRequest__Output, _lirify_v1_GetTrackResponse>;
  
  IndexPlaylist: grpc.handleUnaryCall<_lirify_v1_IndexPlaylistRequest__Output, _lirify_v1_Job>;
  
  IndexPlaylistFromBot: grpc.handleUnaryCall<_lirify_v1_IndexPlaylistFromBotRequest__Output, _lirify_v1_IndexPlaylistFromBotResponse>;
  
  ListTracks: grpc.handleUnaryCall<_lirify_v1_ListTracksRequest__Output, _lirify_v1_ListTracksResponse>;
  
  MatrixPreview: grpc.handleUnaryCall<_lirify_v1_MatrixPreviewRequest__Output, _lirify_v1_MatrixPreviewResponse>;
  
  QueuePlaylists: grpc.handleUnaryCall<_lirify_v1_QueuePlaylistsRequest__Output, _lirify_v1_QueuePlaylistsResponse>;
  
  Recommend: grpc.handleUnaryCall<_lirify_v1_RecommendRequest__Output, _lirify_v1_RecommendResponse>;
  
  RetryFailed: grpc.handleUnaryCall<_lirify_v1_RetryFailedRequest__Output, _lirify_v1_RetryFailedResponse>;
  
  Search: grpc.handleUnaryCall<_lirify_v1_SearchRequest__Output, _lirify_v1_SearchResponse>;
  
  Stream: grpc.handleUnaryCall<_lirify_v1_StreamRequest__Output, _lirify_v1_StreamResponse>;
  
  WatchIndexStats: grpc.handleServerStreamingCall<_lirify_v1_WatchIndexStatsRequest__Output, _lirify_v1_IndexStats>;
  
}

export interface LirifyServiceDefinition extends grpc.ServiceDefinition {
  ExtractVideoIds: MethodDefinition<_lirify_v1_ExtractVideoIdsRequest, _lirify_v1_ExtractVideoIdsResponse, _lirify_v1_ExtractVideoIdsRequest__Output, _lirify_v1_ExtractVideoIdsResponse__Output>
  GetFailedSongs: MethodDefinition<_lirify_v1_GetFailedSongsRequest, _lirify_v1_GetFailedSongsResponse, _lirify_v1_GetFailedSongsRequest__Output, _lirify_v1_GetFailedSongsResponse__Output>
  GetIndexStats: MethodDefinition<_lirify_v1_GetIndexStatsRequest, _lirify_v1_IndexStats, _lirify_v1_GetIndexStatsRequest__Output, _lirify_v1_IndexStats__Output>
  GetJob: MethodDefinition<_lirify_v1_GetJobRequest, _lirify_v1_GetJobResponse, _lirify_v1_GetJobRequest__Output, _lirify_v1_GetJobResponse__Output>
  GetLyrics: MethodDefinition<_lirify_v1_GetLyricsRequest, _lirify_v1_GetLyricsResponse, _lirify_v1_GetLyricsRequest__Output, _lirify_v1_GetLyricsResponse__Output>
  GetTrack: MethodDefinition<_lirify_v1_GetTrackRequest, _lirify_v1_GetTrackResponse, _lirify_v1_GetTrackRequest__Output, _lirify_v1_GetTrackResponse__Output>
  IndexPlaylist: MethodDefinition<_lirify_v1_IndexPlaylistRequest, _lirify_v1_Job, _lirify_v1_IndexPlaylistRequest__Output, _lirify_v1_Job__Output>
  IndexPlaylistFromBot: MethodDefinition<_lirify_v1_IndexPlaylistFromBotRequest, _lirify_v1_IndexPlaylistFromBotResponse, _lirify_v1_IndexPlaylistFromBotRequest__Output, _lirify_v1_IndexPlaylistFromBotResponse__Output>
  ListTracks: MethodDefinition<_lirify_v1_ListTracksRequest, _lirify_v1_ListTracksResponse, _lirify_v1_ListTracksRequest__Output, _lirify_v1_ListTracksResponse__Output>
  MatrixPreview: MethodDefinition<_lirify_v1_MatrixPreviewRequest, _lirify_v1_MatrixPreviewResponse, _lirify_v1_MatrixPreviewRequest__Output, _lirify_v1_MatrixPreviewResponse__Output>
  QueuePlaylists: MethodDefinition<_lirify_v1_QueuePlaylistsRequest, _lirify_v1_QueuePlaylistsResponse, _lirify_v1_QueuePlaylistsRequest__Output, _lirify_v1_QueuePlaylistsResponse__Output>
  Recommend: MethodDefinition<_lirify_v1_RecommendRequest, _lirify_v1_RecommendResponse, _lirify_v1_RecommendRequest__Output, _lirify_v1_RecommendResponse__Output>
  RetryFailed: MethodDefinition<_lirify_v1_RetryFailedRequest, _lirify_v1_RetryFailedResponse, _lirify_v1_RetryFailedRequest__Output, _lirify_v1_RetryFailedResponse__Output>
  Search: MethodDefinition<_lirify_v1_SearchRequest, _lirify_v1_SearchResponse, _lirify_v1_SearchRequest__Output, _lirify_v1_SearchResponse__Output>
  Stream: MethodDefinition<_lirify_v1_StreamRequest, _lirify_v1_StreamResponse, _lirify_v1_StreamRequest__Output, _lirify_v1_StreamResponse__Output>
  WatchIndexStats: MethodDefinition<_lirify_v1_WatchIndexStatsRequest, _lirify_v1_IndexStats, _lirify_v1_WatchIndexStatsRequest__Output, _lirify_v1_IndexStats__Output>
}
