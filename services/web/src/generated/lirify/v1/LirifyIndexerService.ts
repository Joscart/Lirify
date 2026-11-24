// Original file: proto/lirify.proto

import type * as grpc from '@grpc/grpc-js'
import type { MethodDefinition } from '@grpc/proto-loader'
import type { GetLocalIndexRequest as _lirify_v1_GetLocalIndexRequest, GetLocalIndexRequest__Output as _lirify_v1_GetLocalIndexRequest__Output } from '../../lirify/v1/GetLocalIndexRequest';
import type { GetLocalIndexResponse as _lirify_v1_GetLocalIndexResponse, GetLocalIndexResponse__Output as _lirify_v1_GetLocalIndexResponse__Output } from '../../lirify/v1/GetLocalIndexResponse';
import type { PublishToCloudRequest as _lirify_v1_PublishToCloudRequest, PublishToCloudRequest__Output as _lirify_v1_PublishToCloudRequest__Output } from '../../lirify/v1/PublishToCloudRequest';
import type { PublishToCloudResponse as _lirify_v1_PublishToCloudResponse, PublishToCloudResponse__Output as _lirify_v1_PublishToCloudResponse__Output } from '../../lirify/v1/PublishToCloudResponse';

export interface LirifyIndexerServiceClient extends grpc.Client {
  GetLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  GetLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  GetLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  GetLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  getLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  getLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  getLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  getLocalIndex(argument: _lirify_v1_GetLocalIndexRequest, callback: grpc.requestCallback<_lirify_v1_GetLocalIndexResponse__Output>): grpc.ClientUnaryCall;
  
  PublishToCloud(argument: _lirify_v1_PublishToCloudRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  PublishToCloud(argument: _lirify_v1_PublishToCloudRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  PublishToCloud(argument: _lirify_v1_PublishToCloudRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  PublishToCloud(argument: _lirify_v1_PublishToCloudRequest, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  publishToCloud(argument: _lirify_v1_PublishToCloudRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  publishToCloud(argument: _lirify_v1_PublishToCloudRequest, metadata: grpc.Metadata, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  publishToCloud(argument: _lirify_v1_PublishToCloudRequest, options: grpc.CallOptions, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  publishToCloud(argument: _lirify_v1_PublishToCloudRequest, callback: grpc.requestCallback<_lirify_v1_PublishToCloudResponse__Output>): grpc.ClientUnaryCall;
  
}

export interface LirifyIndexerServiceHandlers extends grpc.UntypedServiceImplementation {
  GetLocalIndex: grpc.handleUnaryCall<_lirify_v1_GetLocalIndexRequest__Output, _lirify_v1_GetLocalIndexResponse>;
  
  PublishToCloud: grpc.handleUnaryCall<_lirify_v1_PublishToCloudRequest__Output, _lirify_v1_PublishToCloudResponse>;
  
}

export interface LirifyIndexerServiceDefinition extends grpc.ServiceDefinition {
  GetLocalIndex: MethodDefinition<_lirify_v1_GetLocalIndexRequest, _lirify_v1_GetLocalIndexResponse, _lirify_v1_GetLocalIndexRequest__Output, _lirify_v1_GetLocalIndexResponse__Output>
  PublishToCloud: MethodDefinition<_lirify_v1_PublishToCloudRequest, _lirify_v1_PublishToCloudResponse, _lirify_v1_PublishToCloudRequest__Output, _lirify_v1_PublishToCloudResponse__Output>
}
