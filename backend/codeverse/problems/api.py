"""REST endpoints for tracks and problems (FastAPI)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from ..interview.tracks import TRACKS
from .bank import Difficulty, Track, get_bank

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/tracks")
def list_tracks() -> list[dict]:
    return [t.public() for t in TRACKS.values()]


@router.get("/problems")
def list_problems(
    track: Annotated[Track | None, Query()] = None,
    difficulty: Annotated[Difficulty | None, Query()] = None,
) -> list[dict]:
    return [p.public() for p in get_bank().list(track=track, difficulty=difficulty)]


@router.get("/problems/{problem_id}")
def get_problem(problem_id: str) -> dict:
    p = get_bank().get(problem_id)
    if p is None:
        raise HTTPException(status_code=404, detail="problem not found")
    return p.public()
