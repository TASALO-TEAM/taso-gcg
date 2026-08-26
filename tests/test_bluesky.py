"""Tests del módulo modules/rss/bluesky.py — solo lógica pura (detección de
URL, extracción de actor, mapeo post->entry y embeds), sin llamadas de red.
Mismo criterio de alcance que test_rss_social_style.py."""

from modules.rss.bluesky import BlueskyClient


def test_detecta_link_de_perfil():
    assert BlueskyClient.is_bluesky_url("https://bsky.app/profile/watcher.guru")
    assert BlueskyClient.is_bluesky_url("bsky.app/profile/watcher.guru")
    assert BlueskyClient.is_bluesky_url("https://bsky.app/profile/did:plc:abc123")


def test_no_detecta_otros_links():
    assert not BlueskyClient.is_bluesky_url("https://x.com/watcher.guru")
    assert not BlueskyClient.is_bluesky_url("https://bsky.app/")
    assert not BlueskyClient.is_bluesky_url("")
    assert not BlueskyClient.is_bluesky_url(None)


def test_extrae_actor_de_link_de_perfil():
    assert BlueskyClient._extract_actor("https://bsky.app/profile/watcher.guru") == "watcher.guru"


def test_extrae_actor_de_link_a_post_puntual():
    url = "https://bsky.app/profile/watcher.guru/post/3labcxyz123"
    assert BlueskyClient._extract_actor(url) == "watcher.guru"


def test_post_a_entry_trae_las_llaves_esperadas():
    post = {
        "uri": "at://did:plc:xyz/app.bsky.feed.post/3labc123",
        "author": {"handle": "watcher.guru"},
        "record": {"text": "Bitcoin rompe los 100k"},
        "embed": None,
    }
    entry = BlueskyClient._post_to_entry(post)
    assert entry["title"] == "Bitcoin rompe los 100k"
    assert entry["description"] == "Bitcoin rompe los 100k"
    assert entry["link"] == "https://bsky.app/profile/watcher.guru/post/3labc123"
    assert entry["source"] == "Bluesky / @watcher.guru"
    assert entry["video"] is None
    assert entry["image"] is None
    assert entry["external_link"] is None
    assert entry["hash"]  # no vacío


def test_extrae_imagen_de_embed_de_imagenes():
    embed = {"$type": "app.bsky.embed.images#view", "images": [{"fullsize": "https://cdn.bsky.app/foo.jpg"}]}
    image, external = BlueskyClient._extract_media(embed)
    assert image == "https://cdn.bsky.app/foo.jpg"
    assert external is None


def test_extrae_link_externo_de_embed_de_tarjeta():
    embed = {
        "$type": "app.bsky.embed.external#view",
        "external": {"uri": "https://example.com/articulo", "thumb": "https://cdn.bsky.app/thumb.jpg"},
    }
    image, external = BlueskyClient._extract_media(embed)
    assert image == "https://cdn.bsky.app/thumb.jpg"
    assert external == "https://example.com/articulo"


def test_extrae_miniatura_de_embed_de_video():
    embed = {"$type": "app.bsky.embed.video#view", "thumbnail": "https://cdn.bsky.app/vid-thumb.jpg"}
    image, external = BlueskyClient._extract_media(embed)
    assert image == "https://cdn.bsky.app/vid-thumb.jpg"
    assert external is None


def test_sin_embed_no_rompe():
    assert BlueskyClient._extract_media(None) == (None, None)
