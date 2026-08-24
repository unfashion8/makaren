# -*- coding: utf-8 -*-
"""KOKOROE artwork direction.

This module translates private reading data into qualitative studio directions.
Raw calculation values stay internal and are never presented in the artwork or
customer-facing report.  The vocabulary describes general formal principles
across abstract-art history; it never asks for imitation of a named artist.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


FORMAL_LINEAGES: dict[str, dict[str, str]] = {
    "gestural_field": {
        "logic": (
            "an all-over field of interlaced trajectories whose changes in velocity, "
            "weight, interruption, and gravity preserve evidence of bodily action"
        ),
        "material": (
            "poured and dragged pigment, occasional droplets, dry-brush resistance, "
            "and crossings that accumulate at genuinely different depths"
        ),
    },
    "chromatic_atmosphere": {
        "logic": (
            "large breathing chromatic zones with soft, unstable boundaries; color "
            "must operate as atmosphere and emotional pressure rather than decoration"
        ),
        "material": (
            "multiple translucent veils, thin washes, absorbed stain, and faint color "
            "migration through a visible fibrous ground"
        ),
    },
    "lyrical_space": {
        "logic": (
            "asymmetrical currents that move between concentrated energy and open air, "
            "suggesting weather, distance, and suspended motion without depicting them"
        ),
        "material": (
            "ink-like blooms, vaporous oil glazes, calligraphic pressure changes, "
            "feathered diffusion, and decisive dark accents"
        ),
    },
    "reductive_interval": {
        "logic": (
            "a restrained structure in which pauses, intervals, repetition, and tiny "
            "human irregularities carry as much weight as the visible marks"
        ),
        "material": (
            "muted mineral washes, graphite-like traces, softly abraded bands, and an "
            "unsealed ground whose quiet variations remain perceptible"
        ),
    },
    "relational_void": {
        "logic": (
            "a small number of materially convincing encounters separated by active "
            "voids; every mark must alter the viewer's sense of the surrounding space"
        ),
        "material": (
            "broad loaded strokes that visibly lose pigment, raw ground, compressed "
            "edges, and silence around each event"
        ),
    },
    "geometric_tension": {
        "logic": (
            "proportional tensions among off-axis planes, partial arcs, interrupted "
            "grids, and cropped structures, with no symbol reading as a diagram"
        ),
        "material": (
            "hand-painted edges, uneven opacity, palimpsest underdrawing, and slight "
            "registration shifts that resist vector perfection"
        ),
    },
    "material_event": {
        "logic": (
            "surface changes created by the behavior of matter itself: pressure, "
            "absorption, scraping, pooling, rupture, sediment, and repair"
        ),
        "material": (
            "granular medium, stained fibers, scraped revisions, thin skins beside "
            "impasto ridges, and restrained accidental deposits"
        ),
    },
    "serial_rhythm": {
        "logic": (
            "repeated marks that register duration; the sequence should breathe, drift, "
            "and contain subtle failures rather than becoming a decorative pattern"
        ),
        "material": (
            "successive brush deposits with diminishing load, pressure variation, "
            "ghost marks, and pauses recorded in the surface"
        ),
    },
    "luminous_depth": {
        "logic": (
            "light emerging from within layered color rather than being illustrated, "
            "with ambiguous foreground and background that reward prolonged looking"
        ),
        "material": (
            "scumbled light, translucent glaze, matte passages, submerged marks, and "
            "occasional reflective mineral flecks used with restraint"
        ),
    },
}


PALETTE_DIRECTIONS = (
    "earth pigments, carbon black, bone white, oxidized green, and one restrained warm accent",
    "smoky blue-black, mineral grey, muted umber, fogged violet, and a narrow ember accent",
    "chalk white, weathered indigo, raw sienna, charcoal, and a small acidic counterpoint",
    "deep green-black, clay red, ash grey, translucent ochre, and bruised blue",
    "warm grey, diluted rose earth, dark teal, parchment, and one near-black anchor",
    "night blue, graphite, moss, milky white, and a sparse copper-toned light",
)


SPATIAL_DIRECTIONS = (
    "Keep the visual gravity below center while a lighter current escapes upward.",
    "Build a lateral pressure from one edge and let it dissolve before reaching the other.",
    "Use an off-center quiet zone as the hinge between two unequal fields.",
    "Let a dense passage emerge from a broad atmospheric ground without becoming a focal logo.",
    "Crop several events at the edges so the painting implies a field larger than the canvas.",
    "Use a near-empty upper field and a materially complex lower passage connected by one vulnerable trace.",
)


EDGE_DIRECTIONS = (
    "alternate soaked, lost, scraped, dry, and sharply interrupted edges",
    "let most boundaries breathe and reserve hard edges for a few structural decisions",
    "use bleeding contours beside erasures and partially buried earlier marks",
    "make edges register different drying times, pressure, and pigment load",
)


THEME_GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("変化", "転機", "再出発", "前進", "挑戦"), "renewal under pressure and the courage to change direction"),
    (("関係", "家族", "対人", "共感", "調和"), "closeness, boundaries, and the distance required for genuine relation"),
    (("仕事", "責任", "構造", "判断", "実務"), "structure, responsibility, and the tension between control and responsiveness"),
    (("内省", "静けさ", "自分", "思考", "孤独"), "inward attention, protected silence, and slowly clarifying thought"),
    (("自由", "創造", "表現", "可能性", "拡張"), "expansion, improvisation, and a need for unclaimed space"),
)


def _stable_digest(profile_text: str, numbers: dict[str, Any]) -> bytes:
    payload = json.dumps(numbers or {}, ensure_ascii=False, sort_keys=True, default=str)
    themes = " ".join((profile_text or "").split())[:6000]
    return hashlib.sha256(f"{payload}\n{themes}".encode("utf-8")).digest()


def _private_values(numbers: dict[str, Any], digest: bytes) -> list[int]:
    values: list[int] = []
    for value in (numbers or {}).values():
        match = re.search(r"-?\d+", str(value))
        if match:
            values.append(abs(int(match.group(0))))
    return values or [int(byte) for byte in digest[:12]]


def _theme(profile_text: str, digest: bytes) -> str:
    normalized = " ".join((profile_text or "").split())
    matches = [description for words, description in THEME_GROUPS if any(word in normalized for word in words)]
    if matches:
        return matches[digest[0] % len(matches)]
    return "a protected inner center negotiating with outward movement and changing surroundings"


def build_private_art_direction(profile_text: str, numbers: dict[str, Any]) -> dict[str, Any]:
    """Return reproducible private art direction, including undisclosed scores."""
    digest = _stable_digest(profile_text, numbers)
    values = _private_values(numbers, digest)
    keys = tuple(FORMAL_LINEAGES)

    energy = (sum(values[::2]) * 11 + digest[2]) % 101
    openness = (sum(values[1::2]) * 7 + digest[5]) % 101
    materiality = (sum(values) * 5 + digest[8]) % 101

    if energy >= 67:
        primary_pool = ("gestural_field", "material_event", "lyrical_space")
    elif energy <= 33:
        primary_pool = ("reductive_interval", "relational_void", "luminous_depth")
    else:
        primary_pool = keys
    primary = primary_pool[digest[1] % len(primary_pool)]

    counter_pool = [key for key in keys if key != primary]
    if openness >= 60:
        preferred = ["chromatic_atmosphere", "relational_void", "luminous_depth", "lyrical_space"]
        counter_pool = [key for key in preferred if key != primary]
    elif openness <= 40:
        preferred = ["geometric_tension", "serial_rhythm", "material_event", "gestural_field"]
        counter_pool = [key for key in preferred if key != primary]
    counterpoint = counter_pool[digest[4] % len(counter_pool)]

    discipline_pool = ["reductive_interval", "serial_rhythm", "geometric_tension", "relational_void"]
    discipline_pool = [key for key in discipline_pool if key not in {primary, counterpoint}]
    discipline = discipline_pool[digest[7] % len(discipline_pool)]

    return {
        "private_scores": {
            "energy": energy,
            "openness": openness,
            "materiality": materiality,
        },
        "theme": _theme(profile_text, digest),
        "primary": primary,
        "counterpoint": counterpoint,
        "discipline": discipline,
        "palette": PALETTE_DIRECTIONS[digest[10] % len(PALETTE_DIRECTIONS)],
        "space": SPATIAL_DIRECTIONS[digest[12] % len(SPATIAL_DIRECTIONS)],
        "edges": EDGE_DIRECTIONS[digest[14] % len(EDGE_DIRECTIONS)],
        "surface_emphasis": (
            "pronounced physical relief and abrasion"
            if materiality >= 67
            else "thin-to-thick material contrast"
            if materiality >= 34
            else "subtle absorption, grain, and restrained surface incident"
        ),
    }


def build_studio_prompt(
    profile_text: str,
    numbers: dict[str, Any],
    *,
    previous_prompt: str | None = None,
    revision_instruction: str | None = None,
) -> str:
    """Build an image prompt without exposing private calculation values."""
    direction = build_private_art_direction(profile_text, numbers)
    primary = FORMAL_LINEAGES[direction["primary"]]
    counterpoint = FORMAL_LINEAGES[direction["counterpoint"]]
    discipline = FORMAL_LINEAGES[direction["discipline"]]

    prompt = f"""Create one original, exhibition-grade vertical abstract painting for a private personal-art commission.

CURATORIAL INTENT
Translate this psychological theme into non-illustrative form: {direction['theme']}.

FORMAL ARCHITECTURE
- Primary pictorial logic: {primary['logic']}.
- Counterpoint: {counterpoint['logic']}.
- Compositional discipline: {discipline['logic']}.
- Spatial decision: {direction['space']}
- The image must contain hierarchy, unresolved tension, rhythm, and genuine negative space. Let some passages remain almost empty. Avoid a centered emblem or a collection of equally important objects.

PAINT, SUPPORT, AND TIME
- Primary handling: {primary['material']}.
- Secondary handling: {counterpoint['material']}.
- Restraining method: {discipline['material']}.
- Surface emphasis: {direction['surface_emphasis']}.
- Edge behavior: {direction['edges']}.
- Make drying time, revisions, buried marks, gravity, absorption, pressure, and the resistance of the support visibly credible. The result must look made through successive physical decisions, not assembled from digital primitives.

PICTURE PLANE AND PHYSICAL DEPTH
- Treat the picture plane as conceptually flat: collapse the usual hierarchy between foreground and background, major and minor passages, refined and raw material. Do not use Renaissance perspective or an illustrated 3D scene.
- Within that flat field, build palpable material depth through translucent skins over buried marks, shallow impasto ridges, pooled stains, squeegeed paint, chalky deposits, scraped relief, edge shadows, and restrained matte-to-gloss shifts.
- Depth must come from actual-looking layers of paint and optical color interaction, never from floating CGI objects, bevel effects, drop shadows, or glossy digital extrusion.

COLOR AND LIGHT
- Palette direction: {direction['palette']}.
- Mix pigments optically through transparent and opaque layers. Preserve chromatic mud, scumbling, staining, and small temperature shifts where they add depth. Light must appear to emerge from the paint layers rather than from a digital glow effect.

FRAME-READINESS
- The composition must hold its authority from two to three metres away and reveal new incidents at twenty centimetres: establish clear macro, middle, and micro scales.
- Preserve tonal separation in dark passages and printable color distinction. Avoid dead low-contrast mud, decorative wallpaper, generic luxury-hotel art, and a cheap digital-poster finish.
- Keep the outer five percent crop-safe: no indispensable event may depend on the exact edge, while several secondary traces may still imply a field beyond the canvas.
- Imagine this as a physically framed fine-art print. It must reward prolonged looking and remain convincing at large scale.

OUTPUT
- One full-bleed vertical 2:3 painting, seen straight-on as a high-resolution studio scan or perfectly even documentation of the painted surface.
- No frame, room, wall, mockup, caption, title card, border, or mat.

CRITICAL EXCLUSIONS
- No text, letters, numerals, labels, charts, legends, scores, signatures, logos, seals, or watermarks anywhere.
- No infographic, poster, UI, personality chart, diagram, decorative print, clip art, flat vector geometry, clean Bézier curves, stock gradients, or algorithmic screensaver appearance.
- Do not build the composition from neat translucent circles, rectangles, and lines. Do not use a centered mandala, target, halo, or logo-like ring.
- Do not imitate, quote, or closely reproduce any named artist or existing artwork. Use only the general formal principles above and make a new visual language for this commission.
- No people, faces, bodies, landscapes, objects, symbols with a fixed meaning, or recognizable copyrighted characters."""

    if previous_prompt:
        prompt += (
            "\n\nSERIES CONTINUITY\nPreserve the earlier work's psychological identity while "
            "recomposing it through the current direction. The earlier internal studio brief follows:\n"
            f"{previous_prompt[:5000]}"
        )
    if revision_instruction:
        prompt += (
            "\n\nCLIENT REVISION\nApply the request visibly without turning it into literal "
            "illustration. If the request names an artist, translate it only into broad, "
            "non-identifying formal qualities and do not imitate that artist:\n"
            f"{revision_instruction[:2000]}"
        )
    return prompt
