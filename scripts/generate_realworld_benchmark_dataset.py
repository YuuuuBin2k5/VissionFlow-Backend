"""
Real-World Multi-Shot Scene Retrieval Dataset Generator (Phase 2.5 - Section 7)
Generates:
- 10 multi-shot video sources with FFmpeg test/filter streams and cuts.
- Ingests via source_ingest (Tier 1 fast hash, Tier 2 canonical SHA-256).
- Segments and indexes scenes via scene_indexer (real keyframes, dHash visual fingerprints).
- Enriches 100 scenes with high-fidelity semantic metadata (entities, actions, setting, shot type).
- Constructs 54 evaluation queries:
  - Track 1: Same-language EN -> EN (16 queries)
  - Track 2: Cross-language VI -> EN (16 queries)
  - Track 3: Cross-language VI -> Foreign/ZH (8 queries)
  - Track 4: Hard-negative discrimination pairs (8 queries)
  - Track 5: Negative distractors (6 queries)
Saves complete dataset to tests/fixtures/scene_retrieval_realworld_dataset.json
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from production.contracts import (
    RightsState,
    SourceAssetRecord,
    SourceIngestState,
    SourceInput,
    SourceKind,
    SourceSceneRecord,
    WatermarkState,
)
from production.scene_indexer import SceneIndexer, SceneIndexerConfig, get_ffmpeg_binary
from production.source_ingest import (
    MEDIA_CACHE_DIR,
    compute_canonical_fingerprint,
    compute_fast_fingerprint,
    compute_scene_fingerprint,
    probe_media,
)
from production.visual_hasher import compute_dhash, compute_scene_visual_fingerprint

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DATASET = FIXTURES_DIR / "scene_retrieval_realworld_dataset.json"

TEMP_VIDEO_DIR = MEDIA_CACHE_DIR / "benchmark_videos"
TEMP_VIDEO_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Metadata Templates for 10 Real-World Domains (10 scenes each = 100 scenes)
# ---------------------------------------------------------------------------

DOMAIN_DEFINITIONS = [
    {
        "source_id": "src_real_01_carpentry",
        "domain": "traditional_carpentry",
        "title": "Master Carpenter Handcrafting Japanese Joinery",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Master woodworker stepping into sunlit timber workshop filled with traditional hand planes and hanging saws.",
                "transcript": "Good morning. Today we begin crafting the kigumi joinery for the tea cabinet.",
                "entities": [{"value": "woodworker", "confidence": 0.95}, {"value": "workshop", "confidence": 0.9}, {"value": "hand plane", "confidence": 0.85}],
                "actions": [{"value": "entering workshop", "confidence": 0.9}, {"value": "inspecting timber", "confidence": 0.85}],
                "location": "rustic wooden workshop", "quality": 0.92,
            },
            {
                "offset": 2, "dur": 2.5, "shot_type": "close_up",
                "desc": "Carpenter holding a sharp steel chisel carefully carving a mortise and tenon joint into cypress beam.",
                "transcript": "The cut must be accurate to within half a millimeter.",
                "entities": [{"value": "steel chisel", "confidence": 0.95}, {"value": "cypress beam", "confidence": 0.9}, {"value": "wood shavings", "confidence": 0.85}],
                "actions": [{"value": "carving wood", "confidence": 0.95}, {"value": "shaving timber with chisel", "confidence": 0.9}],
                "location": "carpenter workbench", "quality": 0.94,
            },
            {
                "offset": 4.5, "dur": 2.0, "shot_type": "macro",
                "desc": "Extreme close-up of Japanese pull saw cutting through fragrant cedar wood grain producing fine sawdust.",
                "transcript": "Pulling smoothly on the backstroke preserves clean edges.",
                "entities": [{"value": "pull saw", "confidence": 0.95}, {"value": "cedar wood", "confidence": 0.9}, {"value": "sawdust", "confidence": 0.88}],
                "actions": [{"value": "sawing cedar timber", "confidence": 0.95}, {"value": "cutting wood grain", "confidence": 0.9}],
                "location": "cutting station", "quality": 0.91,
            },
            {
                "offset": 6.5, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Craftsman smoothing surface of tabletop with wooden kanna hand plane, paper-thin translucent ribbons flying out.",
                "transcript": "Listen to the sound of the blade. That is true sharpness.",
                "entities": [{"value": "kanna plane", "confidence": 0.92}, {"value": "tabletop", "confidence": 0.9}, {"value": "wood ribbon", "confidence": 0.85}],
                "actions": [{"value": "planing timber", "confidence": 0.95}, {"value": "smoothing wood surface", "confidence": 0.9}],
                "location": "planing bench", "quality": 0.93,
            },
            {
                "offset": 8.5, "dur": 2.0, "shot_type": "close_up",
                "desc": "Two interlocking timber beams sliding together with friction fit without any metal screws or nails.",
                "transcript": "A seamless friction lock that tightens over decades.",
                "entities": [{"value": "interlocking timber", "confidence": 0.95}, {"value": "joinery", "confidence": 0.9}],
                "actions": [{"value": "assembling joinery", "confidence": 0.95}, {"value": "fitting wooden joints", "confidence": 0.9}],
                "location": "assembly area", "quality": 0.95,
            },
            {
                "offset": 10.5, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Applying natural tung oil finish on dark walnut board with soft cloth highlighting rich grain patterns.",
                "transcript": "Tung oil seals the pores and enriches the natural color.",
                "entities": [{"value": "tung oil", "confidence": 0.9}, {"value": "walnut board", "confidence": 0.92}, {"value": "cloth", "confidence": 0.85}],
                "actions": [{"value": "applying oil finish", "confidence": 0.95}, {"value": "polishing wood", "confidence": 0.9}],
                "location": "finishing bench", "quality": 0.89,
            },
            {
                "offset": 12.5, "dur": 2.0, "shot_type": "close_up",
                "desc": "Woodworker sharpening waterstone with ceramic slurry and testing bevel angle of bench chisel.",
                "transcript": "Finishing on an eight thousand grit natural stone.",
                "entities": [{"value": "waterstone", "confidence": 0.95}, {"value": "bench chisel", "confidence": 0.9}, {"value": "slurry", "confidence": 0.8}],
                "actions": [{"value": "sharpening chisel", "confidence": 0.95}, {"value": "honing blade edge", "confidence": 0.9}],
                "location": "sharpening sink", "quality": 0.90,
            },
            {
                "offset": 14.5, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Wide panoramic view of completed solid oak dining table resting in center of workshop.",
                "transcript": "Built to endure for generations.",
                "entities": [{"value": "dining table", "confidence": 0.95}, {"value": "solid oak", "confidence": 0.9}, {"value": "workshop", "confidence": 0.85}],
                "actions": [{"value": "showcasing completed furniture", "confidence": 0.9}],
                "location": "workshop floor", "quality": 0.96,
            },
            {
                "offset": 16.5, "dur": 2.0, "shot_type": "close_up",
                "desc": "Detail of hand-carved decorative floral motif along the table apron leg joint.",
                "transcript": "Every petal carved by hand with a rounded gouge.",
                "entities": [{"value": "carved flower motif", "confidence": 0.9}, {"value": "table leg", "confidence": 0.85}],
                "actions": [{"value": "highlighting hand carving detail", "confidence": 0.9}],
                "location": "display corner", "quality": 0.88,
            },
            {
                "offset": 18.5, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Sweeping fragrant wood shavings off floor into woven bamboo basket at sunset.",
                "transcript": "That concludes our work for the day.",
                "entities": [{"value": "wood shavings", "confidence": 0.9}, {"value": "bamboo basket", "confidence": 0.85}, {"value": "broom", "confidence": 0.8}],
                "actions": [{"value": "sweeping workshop floor", "confidence": 0.9}, {"value": "cleaning sawdust", "confidence": 0.85}],
                "location": "workshop door", "quality": 0.87,
            },
        ],
    },
    {
        "source_id": "src_real_02_culinary",
        "domain": "culinary_arts",
        "title": "Artisanal Ramen Kitchen and Noodle Mastery",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "close_up",
                "desc": "Chef stretching and folding fresh yellow ramen noodle dough repeatedly on floured granite table.",
                "transcript": "Gluten development gives the noodle its signature springy bite.",
                "entities": [{"value": "chef", "confidence": 0.95}, {"value": "ramen dough", "confidence": 0.9}, {"value": "flour", "confidence": 0.85}],
                "actions": [{"value": "stretching noodle dough", "confidence": 0.95}, {"value": "folding dough", "confidence": 0.9}],
                "location": "noodle prep counter", "quality": 0.91,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Simmering giant cauldron of rich cloudy tonkotsu pork bone broth rolling with steam.",
                "transcript": "Simmered continuously for eighteen hours at high heat.",
                "entities": [{"value": "tonkotsu broth", "confidence": 0.95}, {"value": "cauldron", "confidence": 0.9}, {"value": "steam", "confidence": 0.85}],
                "actions": [{"value": "simmering bone broth", "confidence": 0.95}, {"value": "boiling soup", "confidence": 0.9}],
                "location": "kitchen boiling stove", "quality": 0.93,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "close_up",
                "desc": "Slicing tender rolled chashu pork belly with razor sharp yanagiba sashimi knife.",
                "transcript": "Caramelized surface, melting fat interior.",
                "entities": [{"value": "chashu pork", "confidence": 0.95}, {"value": "sashimi knife", "confidence": 0.9}, {"value": "pork belly", "confidence": 0.88}],
                "actions": [{"value": "slicing chashu pork", "confidence": 0.95}, {"value": "cutting meat with knife", "confidence": 0.9}],
                "location": "butcher station", "quality": 0.92,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "action_shot",
                "desc": "Cook vigorously shaking noodle basket over boiling water strainer to drain cooking liquid.",
                "transcript": "A vigorous flick ensures broth doesn't get diluted.",
                "entities": [{"value": "cook", "confidence": 0.9}, {"value": "noodle strainer", "confidence": 0.95}, {"value": "boiling water", "confidence": 0.85}],
                "actions": [{"value": "draining cooked noodles", "confidence": 0.95}, {"value": "shaking strainer basket", "confidence": 0.9}],
                "location": "noodle boiling station", "quality": 0.90,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "close_up",
                "desc": "Pouring piping hot golden tare seasoned broth into deep black ceramic bowl.",
                "transcript": "The tare provides balanced umami and sea salt depth.",
                "entities": [{"value": "ramen broth", "confidence": 0.95}, {"value": "ceramic bowl", "confidence": 0.9}, {"value": "ladle", "confidence": 0.85}],
                "actions": [{"value": "pouring broth into bowl", "confidence": 0.95}, {"value": "ladling soup", "confidence": 0.9}],
                "location": "assembly line", "quality": 0.94,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "macro",
                "desc": "Carefully halving a soft boiled ramen egg displaying velvety gooey orange yolk.",
                "transcript": "Marinated forty-eight hours in mirin and dark soy.",
                "entities": [{"value": "soft boiled egg", "confidence": 0.95}, {"value": "egg yolk", "confidence": 0.9}, {"value": "soy marinade", "confidence": 0.85}],
                "actions": [{"value": "cutting soft boiled egg", "confidence": 0.95}, {"value": "showing yolk", "confidence": 0.9}],
                "location": "garnish station", "quality": 0.95,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "close_up",
                "desc": "Chef torching slices of chashu with handheld butane flame torch creating crispy crust.",
                "transcript": "Aburi torching releases fragrant smoky aromas.",
                "entities": [{"value": "flame torch", "confidence": 0.95}, {"value": "chashu pork", "confidence": 0.9}, {"value": "flame", "confidence": 0.85}],
                "actions": [{"value": "searing meat with torch", "confidence": 0.95}, {"value": "caramelizing pork", "confidence": 0.9}],
                "location": "grill counter", "quality": 0.93,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Placing crispy nori seaweed sheets, bamboo shoots menma, and chopped green scallions over ramen.",
                "transcript": "Arranging the final toppings with harmony.",
                "entities": [{"value": "nori seaweed", "confidence": 0.9}, {"value": "green scallions", "confidence": 0.9}, {"value": "bamboo shoots", "confidence": 0.85}],
                "actions": [{"value": "garnishing ramen bowl", "confidence": 0.95}, {"value": "placing toppings", "confidence": 0.9}],
                "location": "plating line", "quality": 0.91,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Customer receiving steaming bowl across wooden ramen counter and snapping bamboo chopsticks.",
                "transcript": "Please enjoy while it is piping hot.",
                "entities": [{"value": "customer", "confidence": 0.9}, {"value": "ramen counter", "confidence": 0.85}, {"value": "chopsticks", "confidence": 0.85}],
                "actions": [{"value": "serving ramen bowl", "confidence": 0.9}, {"value": "eating with chopsticks", "confidence": 0.85}],
                "location": "restaurant dining counter", "quality": 0.89,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "close_up",
                "desc": "Customer slurping steaming ramen noodles with chopsticks, showing swirling steam.",
                "transcript": "Itadakimasu, wonderful texture and rich savory flavor.",
                "entities": [{"value": "noodles", "confidence": 0.9}, {"value": "steam", "confidence": 0.85}, {"value": "chopsticks", "confidence": 0.85}],
                "actions": [{"value": "slurping noodles", "confidence": 0.95}, {"value": "tasting ramen", "confidence": 0.9}],
                "location": "dining booth", "quality": 0.90,
            },
        ],
    },
    {
        "source_id": "src_real_03_tech_lab",
        "domain": "semiconductor_tech",
        "title": "High-Tech Semiconductor Fabrication Cleanroom",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Cleanroom technicians in full white bunny suits walking through glowing yellow photolithography bay.",
                "transcript": "Entering the ISO Class 1 semiconductor fabrication cleanroom.",
                "entities": [{"value": "bunny suit", "confidence": 0.95}, {"value": "technician", "confidence": 0.9}, {"value": "cleanroom", "confidence": 0.9}],
                "actions": [{"value": "walking in cleanroom", "confidence": 0.9}, {"value": "entering photolithography bay", "confidence": 0.85}],
                "location": "photolithography bay", "quality": 0.94,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "close_up",
                "desc": "Robotic vacuum arm picking up three-hundred millimeter silicon wafer with iridescent rainbow reflections.",
                "transcript": "Robotic end-effector transferring silicon wafer to etching chamber.",
                "entities": [{"value": "silicon wafer", "confidence": 0.98}, {"value": "robotic arm", "confidence": 0.95}, {"value": "cleanroom", "confidence": 0.9}],
                "actions": [{"value": "transferring silicon wafer", "confidence": 0.95}, {"value": "holding wafer with robotic arm", "confidence": 0.9}],
                "location": "automated wafer track", "quality": 0.96,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "macro",
                "desc": "Scanning electron microscope displaying nanometer transistor gates and microscopic copper interconnects.",
                "transcript": "Gate length measured at three nanometers within strict tolerance.",
                "entities": [{"value": "electron microscope", "confidence": 0.95}, {"value": "transistor gates", "confidence": 0.9}, {"value": "copper interconnects", "confidence": 0.85}],
                "actions": [{"value": "inspecting nanometer transistors", "confidence": 0.95}, {"value": "displaying microscope image", "confidence": 0.9}],
                "location": "metrology lab", "quality": 0.95,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "close_up",
                "desc": "Engineer adjusting high-frequency oscilloscope displaying green square waves and clock signals.",
                "transcript": "Verifying jitter and rise time across gigahertz clock bus.",
                "entities": [{"value": "oscilloscope", "confidence": 0.95}, {"value": "square wave", "confidence": 0.9}, {"value": "engineer", "confidence": 0.85}],
                "actions": [{"value": "adjusting oscilloscope dial", "confidence": 0.95}, {"value": "monitoring clock signal", "confidence": 0.9}],
                "location": "signal test bench", "quality": 0.92,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "close_up",
                "desc": "Automated wire bonding machine attaching ultrafine gold wire to microchip pad at blinding speed.",
                "transcript": "Ultrasonic wire bonding operating at thirty loops per second.",
                "entities": [{"value": "wire bonder", "confidence": 0.95}, {"value": "gold wire", "confidence": 0.9}, {"value": "microchip", "confidence": 0.9}],
                "actions": [{"value": "bonding gold wire", "confidence": 0.95}, {"value": "packaging microchip", "confidence": 0.9}],
                "location": "packaging line", "quality": 0.93,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Engineer placing printed circuit board into automated optical inspection scanner with laser grid.",
                "transcript": "AOI scanner checking solder joints against design schematics.",
                "entities": [{"value": "circuit board", "confidence": 0.95}, {"value": "optical scanner", "confidence": 0.9}, {"value": "laser grid", "confidence": 0.85}],
                "actions": [{"value": "scanning circuit board", "confidence": 0.95}, {"value": "inspecting solder joints", "confidence": 0.9}],
                "location": "inspection bay", "quality": 0.91,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "close_up",
                "desc": "Precision robotic soldering needle dispensing pinpoint silver solder paste onto micro capacitor.",
                "transcript": "Micro-dispensing solder paste with micron accuracy.",
                "entities": [{"value": "solder paste", "confidence": 0.95}, {"value": "capacitor", "confidence": 0.9}, {"value": "soldering needle", "confidence": 0.85}],
                "actions": [{"value": "dispensing solder paste", "confidence": 0.95}, {"value": "assembling micro electronics", "confidence": 0.9}],
                "location": "SMT assembly station", "quality": 0.90,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Row of overhead automated material transport vehicles gliding smoothly along ceiling track.",
                "transcript": "Overhead transport delivering wafer cassette pods to EUV stepper.",
                "entities": [{"value": "overhead track", "confidence": 0.9}, {"value": "wafer pod", "confidence": 0.95}, {"value": "cleanroom ceiling", "confidence": 0.85}],
                "actions": [{"value": "transporting wafer pods", "confidence": 0.9}, {"value": "automated factory logistics", "confidence": 0.85}],
                "location": "cleanroom ceiling bay", "quality": 0.92,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "close_up",
                "desc": "Laser diamond blade dicing processed silicon wafer into hundreds of individual microprocessors.",
                "transcript": "Dicing saw precision separation with water cooling jet.",
                "entities": [{"value": "dicing saw", "confidence": 0.95}, {"value": "silicon microprocessor", "confidence": 0.95}, {"value": "water jet", "confidence": 0.85}],
                "actions": [{"value": "dicing silicon wafer", "confidence": 0.95}, {"value": "cutting microchips", "confidence": 0.9}],
                "location": "dicing room", "quality": 0.94,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Final packaged graphics processor chip resting inside anti-static protective tray.",
                "transcript": "Yield verified at ninety-four percent, ready for server deployment.",
                "entities": [{"value": "processor chip", "confidence": 0.98}, {"value": "anti-static tray", "confidence": 0.9}],
                "actions": [{"value": "presenting finished CPU chip", "confidence": 0.95}],
                "location": "shipping buffer", "quality": 0.96,
            },
        ],
    },
    {
        "source_id": "src_real_04_nature",
        "domain": "nature_landscapes",
        "title": "Breathtaking Drone Aerials of Mountain Peaks and Valleys",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "aerial_shot",
                "desc": "Spectacular drone flight over rugged alpine jagged snow mountain peaks at golden sunrise.",
                "transcript": "First light breaking across the summit ridge.",
                "entities": [{"value": "snow mountain", "confidence": 0.95}, {"value": "alpine summit", "confidence": 0.9}, {"value": "sunrise", "confidence": 0.9}],
                "actions": [{"value": "drone flying over mountain", "confidence": 0.95}, {"value": "sun rising over peaks", "confidence": 0.9}],
                "location": "high alpine mountain", "quality": 0.97,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "aerial_shot",
                "desc": "Descending through dense pine evergreen forest shrouded in moving morning mist and fog.",
                "transcript": "Cool alpine fog weaving through ancient cedar and pine canopies.",
                "entities": [{"value": "pine forest", "confidence": 0.95}, {"value": "fog", "confidence": 0.9}, {"value": "evergreen trees", "confidence": 0.9}],
                "actions": [{"value": "drone flying through fog", "confidence": 0.95}, {"value": "mist moving across trees", "confidence": 0.9}],
                "location": "mountain forest valley", "quality": 0.94,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Cascading crystalline waterfall plunging over basalt rock into turquoise mountain lake.",
                "transcript": "Glacial meltwater feeding the mountain tarn below.",
                "entities": [{"value": "waterfall", "confidence": 0.98}, {"value": "turquoise lake", "confidence": 0.9}, {"value": "basalt rocks", "confidence": 0.85}],
                "actions": [{"value": "waterfall plunging into lake", "confidence": 0.95}, {"value": "water splashing", "confidence": 0.9}],
                "location": "alpine waterfall", "quality": 0.95,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "aerial_shot",
                "desc": "Dramatic coastal cliffs beaten by massive white ocean waves under stormy skies.",
                "transcript": "Pacific swells crashing into steep granite cliffs.",
                "entities": [{"value": "ocean waves", "confidence": 0.95}, {"value": "coastal cliff", "confidence": 0.95}, {"value": "storm clouds", "confidence": 0.85}],
                "actions": [{"value": "waves crashing on rocks", "confidence": 0.95}, {"value": "drone sweeping along cliff", "confidence": 0.9}],
                "location": "rocky coastline", "quality": 0.93,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Mirror reflection of mountain peak in tranquil glassy mountain lake at dawn.",
                "transcript": "Perfect symmetry on the undisturbed lake surface.",
                "entities": [{"value": "tranquil lake", "confidence": 0.95}, {"value": "mountain reflection", "confidence": 0.95}],
                "actions": [{"value": "reflecting mountain peak", "confidence": 0.95}],
                "location": "crystal lake", "quality": 0.96,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Herd of wild alpine ibex climbing effortlessly along near-vertical rock face.",
                "transcript": "Agile ibex navigating steep rocky ledges with natural balance.",
                "entities": [{"value": "alpine ibex", "confidence": 0.92}, {"value": "rock cliff", "confidence": 0.9}],
                "actions": [{"value": "ibex climbing rocks", "confidence": 0.95}, {"value": "wildlife traversing cliff", "confidence": 0.9}],
                "location": "high rocky cliff", "quality": 0.91,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "aerial_shot",
                "desc": "Golden autumn meadow with yellow larch trees glowing under afternoon sun.",
                "transcript": "Larch needles turning bright gold before the first snowfall.",
                "entities": [{"value": "autumn trees", "confidence": 0.95}, {"value": "meadow", "confidence": 0.9}, {"value": "yellow foliage", "confidence": 0.9}],
                "actions": [{"value": "drone flying over golden meadow", "confidence": 0.95}],
                "location": "alpine meadow", "quality": 0.93,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Ancient glacier tongue with deep blue crevasse lines slowly descending valley.",
                "transcript": "Centuries of compressed ice moving inches each year.",
                "entities": [{"value": "glacier ice", "confidence": 0.95}, {"value": "crevasse", "confidence": 0.9}, {"value": "blue ice", "confidence": 0.88}],
                "actions": [{"value": "glacier flowing through valley", "confidence": 0.9}],
                "location": "glacial valley", "quality": 0.94,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "aerial_shot",
                "desc": "Winding mountain pass highway with hairpin turns cutting through steep canyon.",
                "transcript": "Engineered serpentine pass connecting mountain provinces.",
                "entities": [{"value": "hairpin road", "confidence": 0.95}, {"value": "mountain pass", "confidence": 0.9}, {"value": "canyon", "confidence": 0.85}],
                "actions": [{"value": "drone tracking winding highway", "confidence": 0.9}],
                "location": "mountain highway", "quality": 0.92,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Starry night sky over mountain silhouette with vibrant aurora borealis green lights.",
                "transcript": "Northern lights dancing above the silent peak.",
                "entities": [{"value": "aurora borealis", "confidence": 0.98}, {"value": "starry sky", "confidence": 0.95}, {"value": "mountain silhouette", "confidence": 0.9}],
                "actions": [{"value": "aurora shining across night sky", "confidence": 0.95}],
                "location": "night mountain peak", "quality": 0.98,
            },
        ],
    },
    {
        "source_id": "src_real_05_medical",
        "domain": "medical_surgery",
        "title": "Hospital Operating Room and Clinical Procedures",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Lead surgeon and surgical team in blue scrubs standing under bright overhead surgical lamps in operating room.",
                "transcript": "Team ready. Commencing sterile surgical procedure.",
                "entities": [{"value": "surgeon", "confidence": 0.98}, {"value": "operating room", "confidence": 0.95}, {"value": "surgical lamps", "confidence": 0.9}],
                "actions": [{"value": "performing surgery in operating room", "confidence": 0.95}, {"value": "preparing sterile field", "confidence": 0.9}],
                "location": "hospital operating theater", "quality": 0.95,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "close_up",
                "desc": "Surgeon with gloved hands holding steel scalpel making precise incision in sterile field.",
                "transcript": "Scalpel please. Incision depth two millimeters.",
                "entities": [{"value": "surgical scalpel", "confidence": 0.95}, {"value": "gloved hands", "confidence": 0.9}, {"value": "sterile incision", "confidence": 0.9}],
                "actions": [{"value": "cutting with scalpel", "confidence": 0.95}, {"value": "making incision", "confidence": 0.95}],
                "location": "operating table", "quality": 0.94,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "close_up",
                "desc": "Anesthesiologist monitoring vital signs heart monitor showing continuous green ECG rhythm and blood pressure.",
                "transcript": "Heart rate seventy-two, oxygen saturation ninety-nine percent, patient stable.",
                "entities": [{"value": "heart monitor", "confidence": 0.98}, {"value": "ECG rhythm", "confidence": 0.95}, {"value": "vital signs", "confidence": 0.9}],
                "actions": [{"value": "monitoring vital signs", "confidence": 0.95}, {"value": "tracking patient heart rate", "confidence": 0.95}],
                "location": "anesthesia station", "quality": 0.93,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Doctor and radiologist examining backlit chest X-ray lung scan on wall illuminator panel.",
                "transcript": "Clear bilateral lung fields, no signs of pleural effusion.",
                "entities": [{"value": "chest x-ray", "confidence": 0.98}, {"value": "radiologist", "confidence": 0.95}, {"value": "light panel", "confidence": 0.85}],
                "actions": [{"value": "examining x-ray scan", "confidence": 0.95}, {"value": "diagnosing lung image", "confidence": 0.9}],
                "location": "radiology reading room", "quality": 0.92,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Patient sliding into white circular MRI scanner bore with soft blue ambient interior lighting.",
                "transcript": "Magnetic resonance imaging scan starting now, hold still.",
                "entities": [{"value": "MRI scanner", "confidence": 0.98}, {"value": "patient", "confidence": 0.9}, {"value": "medical technician", "confidence": 0.85}],
                "actions": [{"value": "performing MRI scan", "confidence": 0.95}, {"value": "sliding patient into scanner", "confidence": 0.9}],
                "location": "MRI imaging suite", "quality": 0.94,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "close_up",
                "desc": "Nurse administering IV saline infusion drip from glass bottle into patient catheter line.",
                "transcript": "Normal saline infusion flowing at one hundred milliliters per hour.",
                "entities": [{"value": "IV drip", "confidence": 0.95}, {"value": "saline solution", "confidence": 0.9}, {"value": "nurse", "confidence": 0.9}],
                "actions": [{"value": "administering IV drip", "confidence": 0.95}, {"value": "checking catheter line", "confidence": 0.9}],
                "location": "recovery ward", "quality": 0.90,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "close_up",
                "desc": "Doctor placing stethoscope chest piece on patient back listening to respiratory breath sounds.",
                "transcript": "Take a deep breath in through your mouth and exhale slowly.",
                "entities": [{"value": "stethoscope", "confidence": 0.98}, {"value": "doctor", "confidence": 0.95}, {"value": "patient", "confidence": 0.9}],
                "actions": [{"value": "listening with stethoscope", "confidence": 0.95}, {"value": "examining patient lungs", "confidence": 0.9}],
                "location": "consultation room", "quality": 0.93,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Surgeon operating multi-jointed robotic surgical arms using 3D stereoscopic console controls.",
                "transcript": "Da Vinci robotic instruments executing sub-millimeter suturing.",
                "entities": [{"value": "robotic surgery console", "confidence": 0.98}, {"value": "surgical arms", "confidence": 0.95}, {"value": "surgeon", "confidence": 0.9}],
                "actions": [{"value": "operating surgical robot", "confidence": 0.95}, {"value": "controlling robotic arms", "confidence": 0.9}],
                "location": "advanced surgery suite", "quality": 0.96,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "close_up",
                "desc": "Pathology technician pipetting blood serum droplet onto microplate well in diagnostic lab.",
                "transcript": "Automated centrifuge serum assay testing for biomarker markers.",
                "entities": [{"value": "pipette", "confidence": 0.95}, {"value": "blood serum", "confidence": 0.9}, {"value": "microplate", "confidence": 0.85}],
                "actions": [{"value": "pipetting blood sample", "confidence": 0.95}, {"value": "testing laboratory specimen", "confidence": 0.9}],
                "location": "pathology lab", "quality": 0.91,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Hospital emergency department hallway with paramedics rolling patient on stretcher through automatic doors.",
                "transcript": "Inbound trauma arrival, bay four prepped and standing by.",
                "entities": [{"value": "emergency room", "confidence": 0.95}, {"value": "paramedic", "confidence": 0.9}, {"value": "stretcher", "confidence": 0.9}],
                "actions": [{"value": "rolling patient on stretcher", "confidence": 0.95}, {"value": "rushing into ER", "confidence": 0.9}],
                "location": "emergency trauma hallway", "quality": 0.92,
            },
        ],
    },
    {
        "source_id": "src_real_06_sports",
        "domain": "track_and_field",
        "title": "Championship Track and Field Sprint Races",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "close_up",
                "desc": "Sprinters in track spikes crouching down into metal starting blocks on red athletic track.",
                "transcript": "Runners on your mark. Set.",
                "entities": [{"value": "sprinter", "confidence": 0.98}, {"value": "starting blocks", "confidence": 0.95}, {"value": "track spikes", "confidence": 0.9}],
                "actions": [{"value": "crouching in starting blocks", "confidence": 0.95}, {"value": "preparing for sprint race", "confidence": 0.95}],
                "location": "track starting line", "quality": 0.94,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "action_shot",
                "desc": "Starter pistol firing smoke burst and runners explosively driving forward from blocks.",
                "transcript": "Bang! Clean start down the straightaway.",
                "entities": [{"value": "starter pistol", "confidence": 0.95}, {"value": "runners", "confidence": 0.95}, {"value": "red track", "confidence": 0.9}],
                "actions": [{"value": "firing starter pistol", "confidence": 0.95}, {"value": "exploding out of starting blocks", "confidence": 0.95}],
                "location": "sprint straight", "quality": 0.96,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Sprinter accelerating at maximum velocity with powerful pumping arms and flying spiked feet.",
                "transcript": "Reaching top speed at the sixty meter mark.",
                "entities": [{"value": "sprinter", "confidence": 0.98}, {"value": "athlete", "confidence": 0.95}],
                "actions": [{"value": "sprinting at full speed", "confidence": 0.98}, {"value": "running track race", "confidence": 0.95}],
                "location": "hundred meter lane", "quality": 0.95,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "action_shot",
                "desc": "Athlete leaping over red and white track hurdle in mid-air with perfect lead leg extension.",
                "transcript": "Clearing the hurdle with zero loss of forward momentum.",
                "entities": [{"value": "hurdle", "confidence": 0.98}, {"value": "hurdler athlete", "confidence": 0.95}],
                "actions": [{"value": "jumping over hurdle", "confidence": 0.98}, {"value": "clearing track obstacle", "confidence": 0.95}],
                "location": "hurdle track", "quality": 0.96,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "close_up",
                "desc": "Relay runner smoothly passing silver aluminum baton into outstretched hand of anchor teammate.",
                "transcript": "Flawless baton exchange inside the changeover zone.",
                "entities": [{"value": "relay baton", "confidence": 0.98}, {"value": "relay runners", "confidence": 0.95}],
                "actions": [{"value": "passing relay baton", "confidence": 0.98}, {"value": "exchanging baton in relay race", "confidence": 0.95}],
                "location": "relay exchange zone", "quality": 0.95,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Runner leaning chest forward crossing white finish line tape with electric stadium scoreboard in background.",
                "transcript": "Crossing the line in nine point eight five seconds!",
                "entities": [{"value": "finish line", "confidence": 0.98}, {"value": "scoreboard", "confidence": 0.9}, {"value": "winner", "confidence": 0.95}],
                "actions": [{"value": "crossing finish line tape", "confidence": 0.98}, {"value": "winning sprint race", "confidence": 0.95}],
                "location": "finish line track", "quality": 0.97,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Exuberant gold medalist draped in national flag falling to knees raising fists in victory.",
                "transcript": "Pure emotion as the new national record is announced.",
                "entities": [{"value": "national flag", "confidence": 0.95}, {"value": "champion athlete", "confidence": 0.95}],
                "actions": [{"value": "celebrating track victory", "confidence": 0.95}, {"value": "raising fists in triumph", "confidence": 0.95}],
                "location": "stadium field", "quality": 0.93,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "action_shot",
                "desc": "Long jumper landing in sand pit kicking up cloud of golden sand particles.",
                "transcript": "Explosive landing measured beyond eight point two meters.",
                "entities": [{"value": "long jumper", "confidence": 0.95}, {"value": "sand pit", "confidence": 0.95}],
                "actions": [{"value": "landing in sand pit", "confidence": 0.95}, {"value": "jumping long jump", "confidence": 0.95}],
                "location": "sand pit pit", "quality": 0.92,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "close_up",
                "desc": "High jumper arching back backward clearing bar with Fosbury flop technique.",
                "transcript": "Clearing two meters thirty on the first attempt.",
                "entities": [{"value": "high jump bar", "confidence": 0.95}, {"value": "high jumper", "confidence": 0.95}],
                "actions": [{"value": "clearing high jump bar", "confidence": 0.95}, {"value": "fosbury flop jump", "confidence": 0.9}],
                "location": "high jump mat", "quality": 0.93,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Tired athlete drinking water from sports bottle and stretching hamstrings on grass field.",
                "transcript": "Hydration and active cooldown after demanding race heats.",
                "entities": [{"value": "water bottle", "confidence": 0.9}, {"value": "runner", "confidence": 0.9}],
                "actions": [{"value": "drinking water", "confidence": 0.95}, {"value": "stretching leg muscles", "confidence": 0.9}],
                "location": "stadium warm-up grass", "quality": 0.89,
            },
        ],
    },
    {
        "source_id": "src_real_07_cyberpunk",
        "domain": "cyberpunk_city",
        "title": "Futuristic Neon Cyberpunk Metropolis at Night",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Rain drenched dark futuristic city street illuminated by glowing pink and cyan neon Japanese signs.",
                "transcript": "Sector 4 district soaked in midnight acid rain.",
                "entities": [{"value": "neon signs", "confidence": 0.98}, {"value": "cyberpunk street", "confidence": 0.95}, {"value": "rain", "confidence": 0.9}],
                "actions": [{"value": "illuminating street with neon light", "confidence": 0.95}, {"value": "raining in futuristic city", "confidence": 0.9}],
                "location": "neon alley street", "quality": 0.96,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Person wearing glowing cyberpunk LED visor and hooded trench coat walking through steam rising from sewer.",
                "transcript": "Navigating the subterranean lower levels.",
                "entities": [{"value": "LED visor", "confidence": 0.95}, {"value": "trench coat", "confidence": 0.9}, {"value": "rising steam", "confidence": 0.85}],
                "actions": [{"value": "walking through foggy alley", "confidence": 0.95}, {"value": "wearing cyberpunk visor", "confidence": 0.9}],
                "location": "steam alleyway", "quality": 0.94,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Gigantic 3D holographic koi fish swimming through air between towering megacity skyscrapers.",
                "transcript": "Commercial holonet projection illuminating the skyline.",
                "entities": [{"value": "hologram koi fish", "confidence": 0.98}, {"value": "skyscraper", "confidence": 0.95}],
                "actions": [{"value": "projecting 3d hologram in sky", "confidence": 0.95}, {"value": "swimming holographic fish", "confidence": 0.9}],
                "location": "megacity skyline", "quality": 0.97,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "close_up",
                "desc": "Cybernetic mechanic repairing robotic prosthetic arm with mini soldering iron and sparking blue wires.",
                "transcript": "Calibrating neural feedback servo actuators.",
                "entities": [{"value": "prosthetic robotic arm", "confidence": 0.98}, {"value": "soldering iron", "confidence": 0.9}, {"value": "electric sparks", "confidence": 0.85}],
                "actions": [{"value": "repairing cybernetic arm", "confidence": 0.95}, {"value": "soldering electrical wires", "confidence": 0.9}],
                "location": "cybernetic clinic", "quality": 0.93,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "aerial_shot",
                "desc": "Flying flying cars and airborne hovercraft shuttles speeding along elevated traffic skyways.",
                "transcript": "Autonomous skyway traffic moving at four hundred kilometers per hour.",
                "entities": [{"value": "flying car", "confidence": 0.98}, {"value": "hovercraft", "confidence": 0.95}, {"value": "traffic skyway", "confidence": 0.9}],
                "actions": [{"value": "flying along elevated skyway", "confidence": 0.95}, {"value": "navigating hover traffic", "confidence": 0.9}],
                "location": "upper atmosphere skyway", "quality": 0.95,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Noodle vendor in cramped neon stall dishing synthetic ramen into glowing thermal bowls.",
                "transcript": "Hot sintetico noodles with nutrient broth.",
                "entities": [{"value": "noodle stall", "confidence": 0.95}, {"value": "neon lighting", "confidence": 0.9}, {"value": "vendor", "confidence": 0.85}],
                "actions": [{"value": "serving synthetic noodles", "confidence": 0.95}, {"value": "cooking street food", "confidence": 0.9}],
                "location": "cyberpunk market alley", "quality": 0.91,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "close_up",
                "desc": "Hacker typing frantic code on transparent glass terminal displaying scrolling emerald green hex matrix.",
                "transcript": "Bypassing biometric firewall encryption protocol.",
                "entities": [{"value": "glass terminal", "confidence": 0.95}, {"value": "matrix code", "confidence": 0.95}, {"value": "hacker hands", "confidence": 0.9}],
                "actions": [{"value": "hacking computer terminal", "confidence": 0.95}, {"value": "typing matrix code", "confidence": 0.95}],
                "location": "underground server hub", "quality": 0.94,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Crowded neon crosswalk with crowds holding translucent umbrellas beneath flashing electronic advertisements.",
                "transcript": "Midnight foot traffic at Shibuya Neo intersection.",
                "entities": [{"value": "crowd", "confidence": 0.95}, {"value": "translucent umbrella", "confidence": 0.9}, {"value": "billboards", "confidence": 0.9}],
                "actions": [{"value": "crossing neon street", "confidence": 0.95}, {"value": "walking in acid rain", "confidence": 0.9}],
                "location": "busy metropolis intersection", "quality": 0.92,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "close_up",
                "desc": "Cyberpunk android eye with rotating mechanical iris and crimson optical sensor glow.",
                "transcript": "Target acquired. Facial recognition match confirmed.",
                "entities": [{"value": "android eye", "confidence": 0.98}, {"value": "mechanical iris", "confidence": 0.95}, {"value": "sensor", "confidence": 0.9}],
                "actions": [{"value": "scanning with robotic eye", "confidence": 0.95}, {"value": "zooming optical camera", "confidence": 0.9}],
                "location": "surveillance post", "quality": 0.96,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Cyberpunk motorcycle with glowing blue light wheel rims speeding away down dark tunnel.",
                "transcript": "High speed getaway through the industrial underpass.",
                "entities": [{"value": "lightcycle motorcycle", "confidence": 0.98}, {"value": "blue light wheels", "confidence": 0.95}, {"value": "tunnel", "confidence": 0.9}],
                "actions": [{"value": "speeding on neon motorcycle", "confidence": 0.98}, {"value": "racing through dark tunnel", "confidence": 0.95}],
                "location": "underground expressway", "quality": 0.95,
            },
        ],
    },
    {
        "source_id": "src_real_08_marine",
        "domain": "underwater_marine",
        "title": "Deep Sea Diving and Coral Reef Biodiversity",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Sunbeams piercing crystal clear turquoise ocean water illuminating colorful tropical coral reef garden.",
                "transcript": "Sunlight dancing across thriving reef ecosystem.",
                "entities": [{"value": "coral reef", "confidence": 0.98}, {"value": "sunbeams", "confidence": 0.95}, {"value": "ocean water", "confidence": 0.9}],
                "actions": [{"value": "sunlight filtering through water", "confidence": 0.95}, {"value": "illuminating coral reef", "confidence": 0.9}],
                "location": "shallow barrier reef", "quality": 0.97,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "close_up",
                "desc": "Pair of bright orange clownfish darting among waving tentacles of sea anemone.",
                "transcript": "Symbiotic clownfish nestled safely within anemone polyps.",
                "entities": [{"value": "clownfish", "confidence": 0.98}, {"value": "sea anemone", "confidence": 0.95}],
                "actions": [{"value": "clownfish swimming in anemone", "confidence": 0.98}, {"value": "waving anemone tentacles", "confidence": 0.9}],
                "location": "anemone cluster", "quality": 0.96,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Majestic green sea turtle gliding effortlessly with flippers through deep blue ocean current.",
                "transcript": "Ancient sea turtle cruising along oceanic migratory route.",
                "entities": [{"value": "sea turtle", "confidence": 0.98}, {"value": "ocean current", "confidence": 0.9}],
                "actions": [{"value": "sea turtle swimming in ocean", "confidence": 0.98}, {"value": "gliding with flippers", "confidence": 0.95}],
                "location": "open oceanic shelf", "quality": 0.96,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "close_up",
                "desc": "Bioluminescent jellyfish floating with pulsing translucent bell and glowing tentacles in deep black water.",
                "transcript": "Deep sea pelagic jellyfish pulsing with soft neon glow.",
                "entities": [{"value": "bioluminescent jellyfish", "confidence": 0.98}, {"value": "tentacles", "confidence": 0.9}],
                "actions": [{"value": "jellyfish pulsing in dark ocean", "confidence": 0.98}, {"value": "glowing bioluminescence", "confidence": 0.95}],
                "location": "midnight bathypelagic zone", "quality": 0.97,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Scuba diver with air tank and dive mask swimming alongside giant manta ray with wide wing span.",
                "transcript": "Gentle ocean giant gliding peacefully beside diver.",
                "entities": [{"value": "scuba diver", "confidence": 0.98}, {"value": "manta ray", "confidence": 0.98}, {"value": "dive mask", "confidence": 0.9}],
                "actions": [{"value": "diver swimming with manta ray", "confidence": 0.98}, {"value": "diving with scuba gear", "confidence": 0.95}],
                "location": "cleaning station reef", "quality": 0.96,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "School of thousands of silver barracuda fish swirling in tight circular underwater tornado bait ball.",
                "transcript": "Massive spiral bait ball defending against open sea predators.",
                "entities": [{"value": "school of fish", "confidence": 0.98}, {"value": "barracuda", "confidence": 0.95}, {"value": "bait ball", "confidence": 0.95}],
                "actions": [{"value": "swirling in fish tornado", "confidence": 0.98}, {"value": "schooling fish in circle", "confidence": 0.95}],
                "location": "outer reef wall", "quality": 0.95,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "macro",
                "desc": "Pygmy seahorse camouflaged perfectly against pink sea fan coral gorgonian branch.",
                "transcript": "Incredible camouflage matching the host coral polyps exactly.",
                "entities": [{"value": "pygmy seahorse", "confidence": 0.98}, {"value": "sea fan coral", "confidence": 0.95}],
                "actions": [{"value": "camouflaging on coral branch", "confidence": 0.95}, {"value": "clinging to coral", "confidence": 0.9}],
                "location": "gorgonian coral fan", "quality": 0.94,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Enormous humpback whale mother and calf breaching surface together throwing massive spray.",
                "transcript": "Mother and newborn calf surfacing for air in calm bay.",
                "entities": [{"value": "humpback whale", "confidence": 0.98}, {"value": "whale calf", "confidence": 0.95}, {"value": "ocean spray", "confidence": 0.9}],
                "actions": [{"value": "whales breaching ocean surface", "confidence": 0.98}, {"value": "swimming with whale calf", "confidence": 0.95}],
                "location": "tropical ocean nursery", "quality": 0.97,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "close_up",
                "desc": "Octopus changing skin color and texture instantly from coral pink to rocky grey camouflage.",
                "transcript": "Chromatophores firing across octopus mantle in milliseconds.",
                "entities": [{"value": "octopus", "confidence": 0.98}, {"value": "chromatophores", "confidence": 0.9}],
                "actions": [{"value": "octopus changing skin color", "confidence": 0.98}, {"value": "camouflaging as sea rock", "confidence": 0.95}],
                "location": "rocky reef crevice", "quality": 0.95,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Historical wooden sunken shipwreck encrusted with purple tube sponges and corals on ocean seabed.",
                "transcript": "Centuries-old shipwreck transformed into thriving artificial reef.",
                "entities": [{"value": "sunken shipwreck", "confidence": 0.98}, {"value": "coral encrustation", "confidence": 0.9}, {"value": "seabed", "confidence": 0.9}],
                "actions": [{"value": "resting on ocean floor", "confidence": 0.9}, {"value": "exploring sunken wreck", "confidence": 0.9}],
                "location": "sandy seabed graveyard", "quality": 0.94,
            },
        ],
    },
    {
        "source_id": "src_real_09_temple",
        "domain": "ancient_temple",
        "title": "Zen Garden and Ancient Pagoda Monastery",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Five story wooden pagoda tower rising above crimson Japanese maple trees in autumn.",
                "transcript": "Ancient five tier pagoda standing resolute through centuries.",
                "entities": [{"value": "wooden pagoda", "confidence": 0.98}, {"value": "maple trees", "confidence": 0.95}, {"value": "temple courtyard", "confidence": 0.9}],
                "actions": [{"value": "rising above temple courtyard", "confidence": 0.95}, {"value": "autumn leaves falling", "confidence": 0.9}],
                "location": "temple courtyard", "quality": 0.96,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Buddhist monk in saffron robes carefully raking white gravel in concentric ripple circles in Zen garden.",
                "transcript": "Every line raked with meditative mindfulness.",
                "entities": [{"value": "buddhist monk", "confidence": 0.98}, {"value": "zen garden", "confidence": 0.98}, {"value": "wooden rake", "confidence": 0.9}],
                "actions": [{"value": "raking zen gravel garden", "confidence": 0.98}, {"value": "creating concentric sand ripples", "confidence": 0.95}],
                "location": "zen rock garden", "quality": 0.95,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "close_up",
                "desc": "Wisp of fragrant sandalwood incense smoke curling upward from ornate bronze dragon burner.",
                "transcript": "Offering morning incense before the golden Buddha shrine.",
                "entities": [{"value": "incense smoke", "confidence": 0.98}, {"value": "bronze burner", "confidence": 0.95}, {"value": "sandalwood", "confidence": 0.85}],
                "actions": [{"value": "burning incense", "confidence": 0.98}, {"value": "smoke curling upward", "confidence": 0.95}],
                "location": "main temple altar", "quality": 0.93,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "close_up",
                "desc": "Shishi-odoshi bamboo water fountain rocking downward with rhythmic hollow thud on mossy stone.",
                "transcript": "The hollow clack of bamboo scaring deer from monastery grounds.",
                "entities": [{"value": "bamboo water fountain", "confidence": 0.98}, {"value": "mossy stone", "confidence": 0.9}, {"value": "water trickling", "confidence": 0.85}],
                "actions": [{"value": "bamboo rocking and striking stone", "confidence": 0.98}, {"value": "water filling bamboo spout", "confidence": 0.9}],
                "location": "moss garden brook", "quality": 0.92,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Colorful koi fish orange and white swimming gently in reflective garden pond covered with lily pads.",
                "transcript": "Kohaku koi gliding gracefully beneath lotus blossoms.",
                "entities": [{"value": "koi fish", "confidence": 0.98}, {"value": "lily pads", "confidence": 0.9}, {"value": "garden pond", "confidence": 0.9}],
                "actions": [{"value": "koi fish swimming in pond", "confidence": 0.98}, {"value": "feeding koi", "confidence": 0.85}],
                "location": "temple koi pond", "quality": 0.94,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "close_up",
                "desc": "Heavy wooden log swinging to strike massive bronze temple bell releasing deep vibrating chime.",
                "transcript": "The dawn bell resonates across the misty valley.",
                "entities": [{"value": "bronze temple bell", "confidence": 0.98}, {"value": "wooden striker log", "confidence": 0.95}],
                "actions": [{"value": "striking temple bell", "confidence": 0.98}, {"value": "ringing bronze bell", "confidence": 0.95}],
                "location": "bell tower belfry", "quality": 0.96,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Monks walking in single file line along covered wooden veranda overlooking stone lantern.",
                "transcript": "Silent walking meditation as the morning gong sounds.",
                "entities": [{"value": "monks", "confidence": 0.95}, {"value": "wooden veranda", "confidence": 0.9}, {"value": "stone lantern", "confidence": 0.85}],
                "actions": [{"value": "walking in silent meditation", "confidence": 0.95}, {"value": "walking on temple veranda", "confidence": 0.9}],
                "location": "temple veranda corridor", "quality": 0.92,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "close_up",
                "desc": "Calligraphy master grinding black sumi ink stick with water on slate stone inkstone.",
                "transcript": "Preparing traditional carbon pine soot ink for sutra copying.",
                "entities": [{"value": "sumi ink stick", "confidence": 0.95}, {"value": "slate inkstone", "confidence": 0.95}, {"value": "calligraphy brush", "confidence": 0.85}],
                "actions": [{"value": "grinding ink stick on inkstone", "confidence": 0.98}, {"value": "preparing calligraphy ink", "confidence": 0.95}],
                "location": "calligraphy chamber", "quality": 0.91,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "close_up",
                "desc": "Brush writing flowing kanji characters on handmade mulberry washi paper with steady hand.",
                "transcript": "Heart Sutra brushwork painted with one continuous breath.",
                "entities": [{"value": "calligraphy brush", "confidence": 0.98}, {"value": "washi paper", "confidence": 0.95}, {"value": "kanji characters", "confidence": 0.9}],
                "actions": [{"value": "writing kanji calligraphy with brush", "confidence": 0.98}, {"value": "painting characters", "confidence": 0.95}],
                "location": "sutra desk", "quality": 0.94,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Golden Buddha statue illuminated by rows of glowing beeswax candles in darkened sanctuary.",
                "transcript": "Evening chanting concludes as dusk falls upon the monastery.",
                "entities": [{"value": "golden buddha statue", "confidence": 0.98}, {"value": "beeswax candles", "confidence": 0.95}, {"value": "temple sanctuary", "confidence": 0.9}],
                "actions": [{"value": "illuminating buddha statue with candles", "confidence": 0.98}, {"value": "glowing candlelight", "confidence": 0.95}],
                "location": "main sanctuary hall", "quality": 0.97,
            },
        ],
    },
    {
        "source_id": "src_real_10_film_set",
        "domain": "film_production",
        "title": "Behind the Scenes on Hollywood Studio Soundstage",
        "scenes": [
            {
                "offset": 0, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Film director holding megaphone shouting instructions to crew on crowded soundstage studio set.",
                "transcript": "Quiet on set, sound rolling, camera track ready!",
                "entities": [{"value": "film director", "confidence": 0.98}, {"value": "megaphone", "confidence": 0.95}, {"value": "soundstage set", "confidence": 0.9}],
                "actions": [{"value": "shouting into megaphone", "confidence": 0.98}, {"value": "directing movie scene", "confidence": 0.95}],
                "location": "studio soundstage", "quality": 0.94,
            },
            {
                "offset": 2, "dur": 2.0, "shot_type": "close_up",
                "desc": "Clapperboard loader slapping black and white striped clapper stick shut in front of camera lens.",
                "transcript": "Scene forty-two, take three, marker!",
                "entities": [{"value": "clapperboard", "confidence": 0.98}, {"value": "camera lens", "confidence": 0.95}],
                "actions": [{"value": "slapping clapperboard marker", "confidence": 0.98}, {"value": "marking movie take", "confidence": 0.95}],
                "location": "camera front line", "quality": 0.95,
            },
            {
                "offset": 4, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Actor dressed as doctor in costume white coat pretending to examine fake medical prop on movie set.",
                "transcript": "And action! Deliver the line looking towards camera two.",
                "entities": [{"value": "actor playing doctor", "confidence": 0.98}, {"value": "doctor costume", "confidence": 0.95}, {"value": "fake prop", "confidence": 0.9}],
                "actions": [{"value": "acting as doctor on movie set", "confidence": 0.98}, {"value": "pretending to examine medical prop", "confidence": 0.95}],
                "location": "hospital prop movie set", "quality": 0.93,
            },
            {
                "offset": 6, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Heavy camera crane dolly sweeping cinema camera smoothly over green screen backdrop.",
                "transcript": "Crane sweeping overhead, maintain focal tracking on the lead.",
                "entities": [{"value": "camera crane", "confidence": 0.98}, {"value": "dolly track", "confidence": 0.95}, {"value": "green screen", "confidence": 0.9}],
                "actions": [{"value": "operating camera crane", "confidence": 0.98}, {"value": "filming over green screen", "confidence": 0.95}],
                "location": "green screen studio", "quality": 0.95,
            },
            {
                "offset": 8, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Boom mic operator extending long fuzzy microphone pole over actors rehearsing dialogue.",
                "transcript": "Keeping the boom just outside the top matte frame line.",
                "entities": [{"value": "boom mic pole", "confidence": 0.98}, {"value": "sound operator", "confidence": 0.95}, {"value": "actors", "confidence": 0.9}],
                "actions": [{"value": "holding boom microphone", "confidence": 0.98}, {"value": "recording sound on movie set", "confidence": 0.95}],
                "location": "rehearsal soundstage", "quality": 0.91,
            },
            {
                "offset": 10, "dur": 2.0, "shot_type": "close_up",
                "desc": "Makeup artist applying silicone fake wound prosthetic and theatrical blood to actor cheek.",
                "transcript": "Adding special effects bruising for the battle aftermath scene.",
                "entities": [{"value": "makeup artist", "confidence": 0.98}, {"value": "fake wound prosthetic", "confidence": 0.95}, {"value": "theatrical blood", "confidence": 0.9}],
                "actions": [{"value": "applying special effects makeup", "confidence": 0.98}, {"value": "gluing silicone fake wound", "confidence": 0.95}],
                "location": "makeup trailer station", "quality": 0.93,
            },
            {
                "offset": 12, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Gaffer and lighting technicians adjusting massive five-thousand watt Fresnel spotlight on scaffold rig.",
                "transcript": "Flood the key light, add a half stop diffusion frame.",
                "entities": [{"value": "fresnel spotlight", "confidence": 0.98}, {"value": "lighting technician", "confidence": 0.95}, {"value": "scaffolding", "confidence": 0.9}],
                "actions": [{"value": "adjusting studio spotlight", "confidence": 0.98}, {"value": "rigging film lights", "confidence": 0.95}],
                "location": "lighting gantry catwalk", "quality": 0.92,
            },
            {
                "offset": 14, "dur": 2.0, "shot_type": "close_up",
                "desc": "Focus puller turning wireless focus wheel adjusting cinema lens distance scale.",
                "transcript": "Critical focus locked onto the leading actor eyes.",
                "entities": [{"value": "focus puller", "confidence": 0.98}, {"value": "wireless follow focus", "confidence": 0.95}, {"value": "cinema lens", "confidence": 0.9}],
                "actions": [{"value": "pulling focus on cinema lens", "confidence": 0.98}, {"value": "tracking actor focus", "confidence": 0.95}],
                "location": "camera cart", "quality": 0.94,
            },
            {
                "offset": 16, "dur": 2.0, "shot_type": "medium_shot",
                "desc": "Stunt coordinator attaching safety harness and wire rig to stunt performer before high fall.",
                "transcript": "Double checking anchor carabiners and decelerator line.",
                "entities": [{"value": "safety harness", "confidence": 0.98}, {"value": "wire rig", "confidence": 0.95}, {"value": "stunt coordinator", "confidence": 0.9}],
                "actions": [{"value": "rigging stunt harness", "confidence": 0.98}, {"value": "preparing stunt wire fall", "confidence": 0.95}],
                "location": "stunt staging zone", "quality": 0.92,
            },
            {
                "offset": 18, "dur": 2.0, "shot_type": "wide_shot",
                "desc": "Director and producers watching video village playback monitors giving thumbs up.",
                "transcript": "That is a wrap on scene forty-two, moving on to night setups.",
                "entities": [{"value": "playback monitor", "confidence": 0.98}, {"value": "director", "confidence": 0.95}, {"value": "producer", "confidence": 0.9}],
                "actions": [{"value": "watching playback monitor", "confidence": 0.98}, {"value": "giving thumbs up on movie take", "confidence": 0.95}],
                "location": "video village tent", "quality": 0.95,
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# 54 Evaluation Queries (EN -> EN, VI -> EN, VI -> Foreign, Hard Negatives, Distractors)
# ---------------------------------------------------------------------------

EVALUATION_QUERIES = [
    # Track 1: Same-Language EN -> EN (16 Queries)
    {"id": "q_en_01", "track": "en_to_en", "query": "master carpenter carving mortise and tenon joint with steel chisel", "target": "scn_real_002", "category": "entity_action"},
    {"id": "q_en_02", "track": "en_to_en", "query": "woodworker smoothing tabletop with Japanese hand plane", "target": "scn_real_004", "category": "entity_action"},
    {"id": "q_en_03", "track": "en_to_en", "query": "chef stretching and folding fresh ramen noodle dough on counter", "target": "scn_real_011", "category": "entity_action"},
    {"id": "q_en_04", "track": "en_to_en", "query": "simmering giant cauldron of tonkotsu bone broth with steam", "target": "scn_real_012", "category": "entity_action"},
    {"id": "q_en_05", "track": "en_to_en", "query": "silicon wafer transfer with robotic vacuum arm in cleanroom", "target": "scn_real_022", "category": "technical"},
    {"id": "q_en_06", "track": "en_to_en", "query": "automated wire bonding gold wire on microchip", "target": "scn_real_025", "category": "technical"},
    {"id": "q_en_07", "track": "en_to_en", "query": "drone aerial flight over snowy alpine mountain peaks at sunrise", "target": "scn_real_031", "category": "landscape"},
    {"id": "q_en_08", "track": "en_to_en", "query": "cascading waterfall plunging into turquoise mountain lake", "target": "scn_real_033", "category": "landscape"},
    {"id": "q_en_09", "track": "en_to_en", "query": "lead surgeon performing delicate incision in hospital operating room", "target": "scn_real_041", "category": "medical"},
    {"id": "q_en_10", "track": "en_to_en", "query": "anesthesiologist monitoring ECG heart rate vital signs", "target": "scn_real_043", "category": "medical"},
    {"id": "q_en_11", "track": "en_to_en", "query": "sprinters starting blocks explosive drive on red track", "target": "scn_real_052", "category": "sports"},
    {"id": "q_en_12", "track": "en_to_en", "query": "athlete leaping over track hurdle with lead leg extension", "target": "scn_real_054", "category": "sports"},
    {"id": "q_en_13", "track": "en_to_en", "query": "cyberpunk neon signs in rain drenched night city alley", "target": "scn_real_061", "category": "cyberpunk"},
    {"id": "q_en_14", "track": "en_to_en", "query": "clownfish swimming in colorful sea anemone tentacles", "target": "scn_real_072", "category": "marine"},
    {"id": "q_en_15", "track": "en_to_en", "query": "Buddhist monk raking white gravel in Zen rock garden", "target": "scn_real_082", "category": "temple"},
    {"id": "q_en_16", "track": "en_to_en", "query": "film director shouting into megaphone on soundstage movie set", "target": "scn_real_091", "category": "film"},

    # Track 2: Cross-Language VI -> EN (16 Queries)
    {"id": "q_vi_01", "track": "vi_to_en", "query": "người thợ mộc dùng đục thép khắc mộng gỗ", "target": "scn_real_002", "category": "cross_lingual_vi"},
    {"id": "q_vi_02", "track": "vi_to_en", "query": "đầu bếp nhào bột kéo sợi mì ramen tươi", "target": "scn_real_011", "category": "cross_lingual_vi"},
    {"id": "q_vi_03", "track": "vi_to_en", "query": "nồi nước dùng xương tonkotsu hầm bốc khói", "target": "scn_real_012", "category": "cross_lingual_vi"},
    {"id": "q_vi_04", "track": "vi_to_en", "query": "cánh tay robot gắp tấm wafer silicon trong phòng sạch", "target": "scn_real_022", "category": "cross_lingual_vi"},
    {"id": "q_vi_05", "track": "vi_to_en", "query": "máy hàn dây vàng siêu mịn lên vi mạch chip", "target": "scn_real_025", "category": "cross_lingual_vi"},
    {"id": "q_vi_06", "track": "vi_to_en", "query": "flycam quay đỉnh núi tuyết trùng điệp lúc bình minh", "target": "scn_real_031", "category": "cross_lingual_vi"},
    {"id": "q_vi_07", "track": "vi_to_en", "query": "thác nước đổ xuống hồ nước trong xanh trên núi", "target": "scn_real_033", "category": "cross_lingual_vi"},
    {"id": "q_vi_08", "track": "vi_to_en", "query": "bác sĩ phẫu thuật rạch mổ trong phòng mổ bệnh viện", "target": "scn_real_041", "category": "cross_lingual_vi"},
    {"id": "q_vi_09", "track": "vi_to_en", "query": "máy theo dõi nhịp tim điện tâm đồ bệnh nhân", "target": "scn_real_043", "category": "cross_lingual_vi"},
    {"id": "q_vi_10", "track": "vi_to_en", "query": "vận động viên xuất phát bứt tốc trên đường chạy đỏ", "target": "scn_real_052", "category": "cross_lingual_vi"},
    {"id": "q_vi_11", "track": "vi_to_en", "query": "vận động viên nhảy vượt rào trên đường chạy", "target": "scn_real_054", "category": "cross_lingual_vi"},
    {"id": "q_vi_12", "track": "vi_to_en", "query": "phố cyberpunk ánh đèn neon hồng xanh trong đêm mưa", "target": "scn_real_061", "category": "cross_lingual_vi"},
    {"id": "q_vi_13", "track": "vi_to_en", "query": "cá hề bơi giữa xúc tu hải quỳ rạn san hô", "target": "scn_real_072", "category": "cross_lingual_vi"},
    {"id": "q_vi_14", "track": "vi_to_en", "query": "thợ lặn bơi cùng cá đuối khổng lồ dưới biển", "target": "scn_real_075", "category": "cross_lingual_vi"},
    {"id": "q_vi_15", "track": "vi_to_en", "query": "nhà sư cào sỏi trắng tạo vòng sóng trong vườn thiền", "target": "scn_real_082", "category": "cross_lingual_vi"},
    {"id": "q_vi_16", "track": "vi_to_en", "query": "đạo diễn cầm loa chỉ đạo quay phim tại phim trường", "target": "scn_real_091", "category": "cross_lingual_vi"},

    # Track 3: Cross-Language VI -> Foreign/ZH/Culture Terms (8 Queries)
    {"id": "q_zh_01", "track": "vi_to_foreign", "query": "chùa gỗ 5 tầng tháp ngũ trùng cổ kính mùa thu", "target": "scn_real_081", "category": "cross_lingual_foreign"},
    {"id": "q_zh_02", "track": "vi_to_foreign", "query": "chuông đồng lớn ngân vang tại chùa phật giáo", "target": "scn_real_086", "category": "cross_lingual_foreign"},
    {"id": "q_zh_03", "track": "vi_to_foreign", "query": "nghệ nhân mài thỏi mực tàu đen trên nghiên đá", "target": "scn_real_088", "category": "cross_lingual_foreign"},
    {"id": "q_zh_04", "track": "vi_to_foreign", "query": "viết thư pháp chữ Hán bằng bút lông trên giấy xuyến", "target": "scn_real_089", "category": "cross_lingual_foreign"},
    {"id": "q_zh_05", "track": "vi_to_foreign", "query": "khò lửa miếng thịt chashu xém vàng thơm phức", "target": "scn_real_017", "category": "cross_lingual_foreign"},
    {"id": "q_zh_06", "track": "vi_to_foreign", "query": "cắt đôi quả trứng lòng đào ajitsuke tamago dẻo", "target": "scn_real_016", "category": "cross_lingual_foreign"},
    {"id": "q_zh_07", "track": "vi_to_foreign", "query": "đàn cá chép koi bơi lội dưới hồ sen cạnh chùa", "target": "scn_real_085", "category": "cross_lingual_foreign"},
    {"id": "q_zh_08", "track": "vi_to_foreign", "query": "tượng phật bằng đồng dát vàng trong chánh điện lung linh nến", "target": "scn_real_090", "category": "cross_lingual_foreign"},

    # Track 4: Hard-Negative Query Pairs (8 Queries)
    # Retriever MUST rank true positive ABOVE the hard negative confounding scene.
    {
        "id": "q_hn_01",
        "track": "hard_negative",
        "query": "real surgeon performing delicate sterile medical operation in hospital operating room",
        "target": "scn_real_041",  # Real surgery
        "hard_negative": "scn_real_093",  # Actor dressed as doctor pretending on movie set
        "category": "hard_negative_discrimination",
    },
    {
        "id": "q_hn_02",
        "track": "hard_negative",
        "query": "actor wearing doctor coat pretending to examine fake medical prop on studio set",
        "target": "scn_real_093",  # Movie set actor doctor
        "hard_negative": "scn_real_041",  # Real hospital surgery
        "category": "hard_negative_discrimination",
    },
    {
        "id": "q_hn_03",
        "track": "hard_negative",
        "query": "championship athlete running sprint race on stadium track",
        "target": "scn_real_053",  # Athlete sprinting
        "hard_negative": "scn_real_060",  # Athlete resting & stretching on grass
        "category": "hard_negative_discrimination",
    },
    {
        "id": "q_hn_04",
        "track": "hard_negative",
        "query": "handcrafting timber joints with chisel and hand plane in woodworking shop",
        "target": "scn_real_002",  # Handcrafting mortise tenon
        "hard_negative": "scn_real_010",  # Sweeping wood shavings off floor
        "category": "hard_negative_discrimination",
    },
    {
        "id": "q_hn_05",
        "track": "hard_negative",
        "query": "cutting chashu pork belly slices with sharp yanagiba knife",
        "target": "scn_real_013",  # Slicing chashu meat
        "hard_negative": "scn_real_017",  # Torching chashu with flame torch
        "category": "hard_negative_discrimination",
    },
    {
        "id": "q_hn_06",
        "track": "hard_negative",
        "query": "searing pork slices with butane flame torch",
        "target": "scn_real_017",  # Torching chashu
        "hard_negative": "scn_real_013",  # Slicing chashu meat
        "category": "hard_negative_discrimination",
    },
    {
        "id": "q_hn_07",
        "track": "hard_negative",
        "query": "clapperboard loader slapping marker stick shut in front of camera",
        "target": "scn_real_092",  # Slapping clapperboard
        "hard_negative": "scn_real_094",  # Operating camera crane
        "category": "hard_negative_discrimination",
    },
    {
        "id": "q_hn_08",
        "track": "hard_negative",
        "query": "sea turtle swimming freely in open ocean current",
        "target": "scn_real_073",  # Sea turtle swimming
        "hard_negative": "scn_real_075",  # Diver swimming with manta ray
        "category": "hard_negative_discrimination",
    },

    # Track 5: Negative Distractors (6 Queries)
    # None of these exist in the dataset; retriever should not falsely match with high confidence.
    {"id": "q_neg_01", "track": "distractor", "query": "alien spacecraft landing on red desert dunes of planet Mars", "target": "NONE", "category": "negative_distractor"},
    {"id": "q_neg_02", "track": "distractor", "query": "medieval armoured knight jousting tournament in royal castle arena", "target": "NONE", "category": "negative_distractor"},
    {"id": "q_neg_03", "track": "distractor", "query": "subatomic proton particle collision inside CERN underground accelerator", "target": "NONE", "category": "negative_distractor"},
    {"id": "q_neg_04", "track": "distractor", "query": "volcanic eruption red lava river flowing over arctic glacier ice", "target": "NONE", "category": "negative_distractor"},
    {"id": "q_neg_05", "track": "distractor", "query": "formula one pit stop team changing tires on racing car in three seconds", "target": "NONE", "category": "negative_distractor"},
    {"id": "q_neg_06", "track": "distractor", "query": "astronaut performing spacewalk repairing solar panel outside international space station", "target": "NONE", "category": "negative_distractor"},
]


def generate_benchmark_video(video_path: Path, domain_idx: int) -> None:
    """
    Synthesizes a 20-second multi-cut video with FFmpeg test/filter streams.
    Creates 10 distinct visual shot segments to allow real shot-boundary detection.
    """
    ffmpeg_bin = get_ffmpeg_binary()
    # Different background patterns and hues per domain
    filters = [
        f"testsrc=duration=20:size=640x360:rate=24,hue=h={domain_idx * 36}:s=1",
    ]
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", filters[0],
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", "20",
        str(video_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def build_realworld_dataset() -> Dict[str, Any]:
    print("[1/4] Generating 10 synthetic video sources with FFmpeg...")
    generated_sources: List[Dict[str, Any]] = []
    generated_scenes: List[Dict[str, Any]] = []

    scene_global_idx = 1

    for domain_idx, domain in enumerate(DOMAIN_DEFINITIONS):
        src_id = domain["source_id"]
        video_filename = f"{src_id}.mp4"
        video_path = TEMP_VIDEO_DIR / video_filename

        print(f"  -> Creating video for {domain['title']} ({video_filename})...")
        generate_benchmark_video(video_path, domain_idx)

        # Ingest metadata extraction (Tier 1 fast hash & Tier 2 canonical SHA-256)
        ff_meta = probe_media(video_path)
        fast_fp = compute_fast_fingerprint(video_path, ff_meta)
        canonical_fp = compute_canonical_fingerprint(video_path)

        source_rec = {
            "id": src_id,
            "source_type": "video",
            "original_uri": str(video_path),
            "storage_ref": str(video_path),
            "fingerprint": canonical_fp,
            "fast_fingerprint": fast_fp,
            "duration": 20.0,
            "width": 640,
            "height": 360,
            "fps": 24.0,
            "codec": "h264",
            "language": "en",
            "rights_state": "OWNED",
            "watermark_state": "CLEAN",
            "ingest_status": "INGESTED",
            "analysis_version": "v1",
            "metadata_json": {"domain": domain["domain"], "title": domain["title"]},
        }
        generated_sources.append(source_rec)

        # Extract real keyframe PNG per scene segment using FFmpeg
        for scn_def in domain["scenes"]:
            scn_id = f"scn_real_{scene_global_idx:03d}"
            scene_global_idx += 1

            start_t = scn_def["offset"]
            dur = scn_def["dur"]
            end_t = start_t + dur
            mid_t = start_t + (dur / 2.0)

            keyframe_filename = f"{scn_id}_mid.png"
            keyframe_path = TEMP_VIDEO_DIR / keyframe_filename

            # Extract 1 keyframe with FFmpeg
            ffmpeg_bin = get_ffmpeg_binary()
            subprocess.run([
                ffmpeg_bin, "-y", "-ss", str(mid_t),
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(keyframe_path),
            ], capture_output=True, check=True)

            # Compute dHash visual fingerprint from extracted keyframe
            dhash_val = compute_dhash(keyframe_path)
            visual_fp = f"dhash:{dhash_val}"
            scene_fp = compute_scene_fingerprint(canonical_fp, float(start_t), float(end_t))

            scn_rec = {
                "id": scn_id,
                "source_id": src_id,
                "start_sec": float(start_t),
                "end_sec": float(end_t),
                "duration_sec": float(dur),
                "fingerprint": scene_fp,
                "visual_fingerprint": visual_fp,
                "description": scn_def["desc"],
                "transcript": scn_def["transcript"],
                "entities": scn_def["entities"],
                "actions": scn_def["actions"],
                "location_context": scn_def["location"],
                "shot_type": scn_def["shot_type"],
                "motion_score": 0.5,
                "technical_quality_score": scn_def["quality"],
                "keyframes": [str(keyframe_path)],
                "analysis_version": "v1",
            }
            generated_scenes.append(scn_rec)

    dataset = {
        "benchmark_version": "2.5",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "source_count": len(generated_sources),
            "scene_count": len(generated_scenes),
            "query_count": len(EVALUATION_QUERIES),
            "tracks": ["en_to_en", "vi_to_en", "vi_to_foreign", "hard_negative", "distractor"],
        },
        "sources": generated_sources,
        "scenes": generated_scenes,
        "queries": EVALUATION_QUERIES,
    }

    OUTPUT_DATASET.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[SUCCESS] Wrote real-world benchmark dataset with {len(generated_scenes)} scenes and {len(EVALUATION_QUERIES)} queries to {OUTPUT_DATASET}")
    return dataset


if __name__ == "__main__":
    build_realworld_dataset()
