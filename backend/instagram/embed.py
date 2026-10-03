"""Instagram public embed parsing and profile source."""

import json
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from backend.instagram_urls import profile_url
from backend.models.instagram.embed import EmbedContext, EmbedPosts
from backend.models.media import InstagramPost, InstagramProfile


class _EmbedScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        self.in_script = tag == "script"

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)


def walk_context(value):
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key == "contextJSON":
                child = json.loads(child)
            yield from walk_context(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_context(child)


def script_json_candidates(script):
    """Instagram serves JSON scripts and JavaScript .handle(JSON) calls."""
    candidates = script.split(".handle(")[1:]
    if script.lstrip().startswith(("{", "[")):
        candidates.append(script)
    return candidates


def _embed_nodes(payload: str) -> list[dict]:
    """Decode the heterogeneous ServerJS envelope at the external-data boundary."""

    parser = _EmbedScripts()
    parser.feed(payload)
    decoder = json.JSONDecoder()
    nodes = []
    for script in parser.scripts:
        for candidate in script_json_candidates(script):
            value, _ = decoder.raw_decode(candidate.lstrip())
            nodes.extend(walk_context(value))
    return nodes


def _embed_context(payload: str) -> dict:
    contexts = [node for node in _embed_nodes(payload) if "graphql_media" in node]
    if len(contexts) != 1:
        raise ValueError("Expected exactly one Instagram media context")
    return contexts[0]


def extract_embed_posts(payload: str) -> list[InstagramPost]:
    return EmbedPosts.model_validate(_embed_context(payload)).posts()


def public_embed_profile(handle: str) -> InstagramProfile:
    request = Request(f"{profile_url(handle)}embed/", headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        payload = response.read(2_000_000).decode("utf-8")
    context = EmbedContext.model_validate(_embed_context(payload))
    if context.user.username != handle[1:]:
        raise ValueError(f"Instagram profile not found: {handle}")
    return context.user.to_profile(context.posts())
