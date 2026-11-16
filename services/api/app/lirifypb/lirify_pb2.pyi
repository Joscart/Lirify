from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Track(_message.Message):
    __slots__ = ("video_id", "title", "artist", "language", "backend", "youtube_title", "duration", "lyrics", "synced", "thumb", "stream_url")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    ARTIST_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    BACKEND_FIELD_NUMBER: _ClassVar[int]
    YOUTUBE_TITLE_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    LYRICS_FIELD_NUMBER: _ClassVar[int]
    SYNCED_FIELD_NUMBER: _ClassVar[int]
    THUMB_FIELD_NUMBER: _ClassVar[int]
    STREAM_URL_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    title: str
    artist: str
    language: str
    backend: str
    youtube_title: str
    duration: float
    lyrics: str
    synced: bool
    thumb: str
    stream_url: str
    def __init__(self, video_id: _Optional[str] = ..., title: _Optional[str] = ..., artist: _Optional[str] = ..., language: _Optional[str] = ..., backend: _Optional[str] = ..., youtube_title: _Optional[str] = ..., duration: _Optional[float] = ..., lyrics: _Optional[str] = ..., synced: bool = ..., thumb: _Optional[str] = ..., stream_url: _Optional[str] = ...) -> None: ...

class TrackSummary(_message.Message):
    __slots__ = ("video_id", "title", "artist", "language", "score", "thumb", "duration")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    ARTIST_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    THUMB_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    title: str
    artist: str
    language: str
    score: float
    thumb: str
    duration: float
    def __init__(self, video_id: _Optional[str] = ..., title: _Optional[str] = ..., artist: _Optional[str] = ..., language: _Optional[str] = ..., score: _Optional[float] = ..., thumb: _Optional[str] = ..., duration: _Optional[float] = ...) -> None: ...

class Job(_message.Message):
    __slots__ = ("job_id", "action", "url", "status", "stage", "error", "added", "attempts", "source", "created_at", "updated_at")
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    ADDED_FIELD_NUMBER: _ClassVar[int]
    ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    action: str
    url: str
    status: str
    stage: str
    error: str
    added: int
    attempts: int
    source: str
    created_at: int
    updated_at: int
    def __init__(self, job_id: _Optional[str] = ..., action: _Optional[str] = ..., url: _Optional[str] = ..., status: _Optional[str] = ..., stage: _Optional[str] = ..., error: _Optional[str] = ..., added: _Optional[int] = ..., attempts: _Optional[int] = ..., source: _Optional[str] = ..., created_at: _Optional[int] = ..., updated_at: _Optional[int] = ...) -> None: ...

class SearchRequest(_message.Message):
    __slots__ = ("query", "limit")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    query: str
    limit: int
    def __init__(self, query: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class SearchResponse(_message.Message):
    __slots__ = ("query", "results")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    query: str
    results: _containers.RepeatedCompositeFieldContainer[TrackSummary]
    def __init__(self, query: _Optional[str] = ..., results: _Optional[_Iterable[_Union[TrackSummary, _Mapping]]] = ...) -> None: ...

class RecommendRequest(_message.Message):
    __slots__ = ("video_id", "limit", "seed_video_ids")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    SEED_VIDEO_IDS_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    limit: int
    seed_video_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, video_id: _Optional[str] = ..., limit: _Optional[int] = ..., seed_video_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class RecommendResponse(_message.Message):
    __slots__ = ("seed_video_id", "recommendations", "engine")
    SEED_VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    RECOMMENDATIONS_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    seed_video_id: str
    recommendations: _containers.RepeatedCompositeFieldContainer[TrackSummary]
    engine: str
    def __init__(self, seed_video_id: _Optional[str] = ..., recommendations: _Optional[_Iterable[_Union[TrackSummary, _Mapping]]] = ..., engine: _Optional[str] = ...) -> None: ...

class GetTrackRequest(_message.Message):
    __slots__ = ("video_id", "include_lyrics")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_LYRICS_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    include_lyrics: bool
    def __init__(self, video_id: _Optional[str] = ..., include_lyrics: bool = ...) -> None: ...

class GetTrackResponse(_message.Message):
    __slots__ = ("track",)
    TRACK_FIELD_NUMBER: _ClassVar[int]
    track: Track
    def __init__(self, track: _Optional[_Union[Track, _Mapping]] = ...) -> None: ...

class ListTracksRequest(_message.Message):
    __slots__ = ("offset", "limit", "language")
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    offset: int
    limit: int
    language: str
    def __init__(self, offset: _Optional[int] = ..., limit: _Optional[int] = ..., language: _Optional[str] = ...) -> None: ...

class ListTracksResponse(_message.Message):
    __slots__ = ("total", "tracks")
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    TRACKS_FIELD_NUMBER: _ClassVar[int]
    total: int
    tracks: _containers.RepeatedCompositeFieldContainer[Track]
    def __init__(self, total: _Optional[int] = ..., tracks: _Optional[_Iterable[_Union[Track, _Mapping]]] = ...) -> None: ...

class LyricsLine(_message.Message):
    __slots__ = ("time_ms", "text")
    TIME_MS_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    time_ms: int
    text: str
    def __init__(self, time_ms: _Optional[int] = ..., text: _Optional[str] = ...) -> None: ...

class GetLyricsRequest(_message.Message):
    __slots__ = ("video_id",)
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    def __init__(self, video_id: _Optional[str] = ...) -> None: ...

class GetLyricsResponse(_message.Message):
    __slots__ = ("video_id", "synced", "lines", "raw", "language")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    SYNCED_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    RAW_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    synced: bool
    lines: _containers.RepeatedCompositeFieldContainer[LyricsLine]
    raw: str
    language: str
    def __init__(self, video_id: _Optional[str] = ..., synced: bool = ..., lines: _Optional[_Iterable[_Union[LyricsLine, _Mapping]]] = ..., raw: _Optional[str] = ..., language: _Optional[str] = ...) -> None: ...

class StreamRequest(_message.Message):
    __slots__ = ("video_id", "probe")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    PROBE_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    probe: bool
    def __init__(self, video_id: _Optional[str] = ..., probe: bool = ...) -> None: ...

class StreamResponse(_message.Message):
    __slots__ = ("video_id", "url", "duration", "expires_at")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    url: str
    duration: float
    expires_at: int
    def __init__(self, video_id: _Optional[str] = ..., url: _Optional[str] = ..., duration: _Optional[float] = ..., expires_at: _Optional[int] = ...) -> None: ...

class IndexPlaylistRequest(_message.Message):
    __slots__ = ("playlist_url", "limit", "source")
    PLAYLIST_URL_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    playlist_url: str
    limit: int
    source: str
    def __init__(self, playlist_url: _Optional[str] = ..., limit: _Optional[int] = ..., source: _Optional[str] = ...) -> None: ...

class QueuePlaylistsRequest(_message.Message):
    __slots__ = ("playlist_urls", "limit", "source")
    PLAYLIST_URLS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    playlist_urls: _containers.RepeatedScalarFieldContainer[str]
    limit: int
    source: str
    def __init__(self, playlist_urls: _Optional[_Iterable[str]] = ..., limit: _Optional[int] = ..., source: _Optional[str] = ...) -> None: ...

class QueuePlaylistsResponse(_message.Message):
    __slots__ = ("jobs", "queue_size")
    JOBS_FIELD_NUMBER: _ClassVar[int]
    QUEUE_SIZE_FIELD_NUMBER: _ClassVar[int]
    jobs: _containers.RepeatedCompositeFieldContainer[Job]
    queue_size: int
    def __init__(self, jobs: _Optional[_Iterable[_Union[Job, _Mapping]]] = ..., queue_size: _Optional[int] = ...) -> None: ...

class GetJobRequest(_message.Message):
    __slots__ = ("job_id",)
    JOB_ID_FIELD_NUMBER: _ClassVar[int]
    job_id: str
    def __init__(self, job_id: _Optional[str] = ...) -> None: ...

class ExtractVideoIdsRequest(_message.Message):
    __slots__ = ("playlist_url", "limit")
    PLAYLIST_URL_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    playlist_url: str
    limit: int
    def __init__(self, playlist_url: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class ExtractVideoIdsResponse(_message.Message):
    __slots__ = ("count", "video_ids")
    COUNT_FIELD_NUMBER: _ClassVar[int]
    VIDEO_IDS_FIELD_NUMBER: _ClassVar[int]
    count: int
    video_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, count: _Optional[int] = ..., video_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class GetJobResponse(_message.Message):
    __slots__ = ("job",)
    JOB_FIELD_NUMBER: _ClassVar[int]
    job: Job
    def __init__(self, job: _Optional[_Union[Job, _Mapping]] = ...) -> None: ...

class GetIndexStatsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class IndexStats(_message.Message):
    __slots__ = ("indexed_songs", "video_ids", "vocabulary_size", "inverted_terms", "lyrics_tokens", "languages", "backends", "playlist_pending", "matrix_pending", "failed_songs", "cached_lyrics", "jobs", "matrices_available", "weights", "generated_at", "lyrics_providers", "top_terms", "stateless", "tracks_store", "vectors_store", "max_indexed_songs")
    class LanguagesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    class BackendsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    class WeightsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    INDEXED_SONGS_FIELD_NUMBER: _ClassVar[int]
    VIDEO_IDS_FIELD_NUMBER: _ClassVar[int]
    VOCABULARY_SIZE_FIELD_NUMBER: _ClassVar[int]
    INVERTED_TERMS_FIELD_NUMBER: _ClassVar[int]
    LYRICS_TOKENS_FIELD_NUMBER: _ClassVar[int]
    LANGUAGES_FIELD_NUMBER: _ClassVar[int]
    BACKENDS_FIELD_NUMBER: _ClassVar[int]
    PLAYLIST_PENDING_FIELD_NUMBER: _ClassVar[int]
    MATRIX_PENDING_FIELD_NUMBER: _ClassVar[int]
    FAILED_SONGS_FIELD_NUMBER: _ClassVar[int]
    CACHED_LYRICS_FIELD_NUMBER: _ClassVar[int]
    JOBS_FIELD_NUMBER: _ClassVar[int]
    MATRICES_AVAILABLE_FIELD_NUMBER: _ClassVar[int]
    WEIGHTS_FIELD_NUMBER: _ClassVar[int]
    GENERATED_AT_FIELD_NUMBER: _ClassVar[int]
    LYRICS_PROVIDERS_FIELD_NUMBER: _ClassVar[int]
    TOP_TERMS_FIELD_NUMBER: _ClassVar[int]
    STATELESS_FIELD_NUMBER: _ClassVar[int]
    TRACKS_STORE_FIELD_NUMBER: _ClassVar[int]
    VECTORS_STORE_FIELD_NUMBER: _ClassVar[int]
    MAX_INDEXED_SONGS_FIELD_NUMBER: _ClassVar[int]
    indexed_songs: int
    video_ids: int
    vocabulary_size: int
    inverted_terms: int
    lyrics_tokens: int
    languages: _containers.ScalarMap[str, int]
    backends: _containers.ScalarMap[str, int]
    playlist_pending: int
    matrix_pending: int
    failed_songs: int
    cached_lyrics: int
    jobs: _containers.RepeatedCompositeFieldContainer[Job]
    matrices_available: _containers.RepeatedScalarFieldContainer[str]
    weights: _containers.ScalarMap[str, float]
    generated_at: int
    lyrics_providers: _containers.RepeatedScalarFieldContainer[str]
    top_terms: _containers.RepeatedScalarFieldContainer[str]
    stateless: bool
    tracks_store: str
    vectors_store: str
    max_indexed_songs: int
    def __init__(self, indexed_songs: _Optional[int] = ..., video_ids: _Optional[int] = ..., vocabulary_size: _Optional[int] = ..., inverted_terms: _Optional[int] = ..., lyrics_tokens: _Optional[int] = ..., languages: _Optional[_Mapping[str, int]] = ..., backends: _Optional[_Mapping[str, int]] = ..., playlist_pending: _Optional[int] = ..., matrix_pending: _Optional[int] = ..., failed_songs: _Optional[int] = ..., cached_lyrics: _Optional[int] = ..., jobs: _Optional[_Iterable[_Union[Job, _Mapping]]] = ..., matrices_available: _Optional[_Iterable[str]] = ..., weights: _Optional[_Mapping[str, float]] = ..., generated_at: _Optional[int] = ..., lyrics_providers: _Optional[_Iterable[str]] = ..., top_terms: _Optional[_Iterable[str]] = ..., stateless: bool = ..., tracks_store: _Optional[str] = ..., vectors_store: _Optional[str] = ..., max_indexed_songs: _Optional[int] = ...) -> None: ...

class WatchIndexStatsRequest(_message.Message):
    __slots__ = ("interval_seconds",)
    INTERVAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    interval_seconds: int
    def __init__(self, interval_seconds: _Optional[int] = ...) -> None: ...

class FailedSong(_message.Message):
    __slots__ = ("video_id", "title", "artist", "reason", "attempts", "last_try", "duration")
    VIDEO_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    ARTIST_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    LAST_TRY_FIELD_NUMBER: _ClassVar[int]
    DURATION_FIELD_NUMBER: _ClassVar[int]
    video_id: str
    title: str
    artist: str
    reason: str
    attempts: int
    last_try: int
    duration: float
    def __init__(self, video_id: _Optional[str] = ..., title: _Optional[str] = ..., artist: _Optional[str] = ..., reason: _Optional[str] = ..., attempts: _Optional[int] = ..., last_try: _Optional[int] = ..., duration: _Optional[float] = ...) -> None: ...

class GetFailedSongsRequest(_message.Message):
    __slots__ = ("limit",)
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    limit: int
    def __init__(self, limit: _Optional[int] = ...) -> None: ...

class GetFailedSongsResponse(_message.Message):
    __slots__ = ("total", "cached_lyrics", "max_attempts", "retry_interval_seconds", "failed")
    TOTAL_FIELD_NUMBER: _ClassVar[int]
    CACHED_LYRICS_FIELD_NUMBER: _ClassVar[int]
    MAX_ATTEMPTS_FIELD_NUMBER: _ClassVar[int]
    RETRY_INTERVAL_SECONDS_FIELD_NUMBER: _ClassVar[int]
    FAILED_FIELD_NUMBER: _ClassVar[int]
    total: int
    cached_lyrics: int
    max_attempts: int
    retry_interval_seconds: int
    failed: _containers.RepeatedCompositeFieldContainer[FailedSong]
    def __init__(self, total: _Optional[int] = ..., cached_lyrics: _Optional[int] = ..., max_attempts: _Optional[int] = ..., retry_interval_seconds: _Optional[int] = ..., failed: _Optional[_Iterable[_Union[FailedSong, _Mapping]]] = ...) -> None: ...

class RetryFailedRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RetryFailedResponse(_message.Message):
    __slots__ = ("started", "already_running", "message")
    STARTED_FIELD_NUMBER: _ClassVar[int]
    ALREADY_RUNNING_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    started: bool
    already_running: bool
    message: str
    def __init__(self, started: bool = ..., already_running: bool = ..., message: _Optional[str] = ...) -> None: ...

class MatrixPreviewRequest(_message.Message):
    __slots__ = ("size",)
    SIZE_FIELD_NUMBER: _ClassVar[int]
    size: int
    def __init__(self, size: _Optional[int] = ...) -> None: ...

class MatrixPreviewRow(_message.Message):
    __slots__ = ("values",)
    VALUES_FIELD_NUMBER: _ClassVar[int]
    values: _containers.RepeatedScalarFieldContainer[float]
    def __init__(self, values: _Optional[_Iterable[float]] = ...) -> None: ...

class MatrixPreview(_message.Message):
    __slots__ = ("shape", "rows")
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    ROWS_FIELD_NUMBER: _ClassVar[int]
    shape: _containers.RepeatedScalarFieldContainer[int]
    rows: _containers.RepeatedCompositeFieldContainer[MatrixPreviewRow]
    def __init__(self, shape: _Optional[_Iterable[int]] = ..., rows: _Optional[_Iterable[_Union[MatrixPreviewRow, _Mapping]]] = ...) -> None: ...

class MatrixPreviewResponse(_message.Message):
    __slots__ = ("shape", "size", "songs", "matrices", "weights")
    class MatricesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: MatrixPreview
        def __init__(self, key: _Optional[str] = ..., value: _Optional[_Union[MatrixPreview, _Mapping]] = ...) -> None: ...
    class WeightsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    SONGS_FIELD_NUMBER: _ClassVar[int]
    MATRICES_FIELD_NUMBER: _ClassVar[int]
    WEIGHTS_FIELD_NUMBER: _ClassVar[int]
    shape: _containers.RepeatedScalarFieldContainer[int]
    size: int
    songs: _containers.RepeatedCompositeFieldContainer[TrackSummary]
    matrices: _containers.MessageMap[str, MatrixPreview]
    weights: _containers.ScalarMap[str, float]
    def __init__(self, shape: _Optional[_Iterable[int]] = ..., size: _Optional[int] = ..., songs: _Optional[_Iterable[_Union[TrackSummary, _Mapping]]] = ..., matrices: _Optional[_Mapping[str, MatrixPreview]] = ..., weights: _Optional[_Mapping[str, float]] = ...) -> None: ...

class IndexPlaylistFromBotRequest(_message.Message):
    __slots__ = ("playlist_url", "source_bot", "idempotency_key", "limit")
    PLAYLIST_URL_FIELD_NUMBER: _ClassVar[int]
    SOURCE_BOT_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    playlist_url: str
    source_bot: str
    idempotency_key: str
    limit: int
    def __init__(self, playlist_url: _Optional[str] = ..., source_bot: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class IndexPlaylistFromBotResponse(_message.Message):
    __slots__ = ("accepted", "job", "job_status_url")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    JOB_FIELD_NUMBER: _ClassVar[int]
    JOB_STATUS_URL_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    job: Job
    job_status_url: str
    def __init__(self, accepted: bool = ..., job: _Optional[_Union[Job, _Mapping]] = ..., job_status_url: _Optional[str] = ...) -> None: ...
