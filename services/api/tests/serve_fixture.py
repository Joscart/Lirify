"""Run the real FastAPI app with a deterministic, in-memory song index."""

import uvicorn

from test_course_search import catalogue, main, song


if __name__ == "__main__":
    songs = [
        *(song(i, f"[00:02.50]Mi amor es eterno, luces {i}.") for i in range(10)),
        *(song(i, f"La noche tiene un eco eterno {i}.") for i in range(10, 14)),
    ]
    main.STATE.update(catalogue(songs), ids=[item["video_id"] for item in songs])
    uvicorn.run(main.app, host="127.0.0.1", port=8000, lifespan="off")
