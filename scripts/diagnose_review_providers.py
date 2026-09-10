"""Read-only Pexels search/scoring diagnostic. Does not create runs or write caches.

Uses only PEXELS_API_KEY from local configuration. No production database access.
"""
import asyncio
import json
import os
from pathlib import Path
import sys


async def main():
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    import dotenv
    values = {**dotenv.dotenv_values(backend / '.env'),
              **dotenv.dotenv_values(backend / 'services/control-plane/.env'), **os.environ}
    key = values.get('PEXELS_API_KEY')
    dotenv.load_dotenv = lambda *args, **kwargs: False
    os.environ['VISIONFLOW_USE_DEV_REPOSITORIES'] = '1'
    os.environ['DATABASE_URL'] = 'postgresql://unused@127.0.0.1:1/unused'
    from production.asset_resolver import PexelsStockAdapter, CandidateScorer
    from production.contracts import VisualIntent
    adapter = PexelsStockAdapter()
    adapter.api_key = key
    scorer = CandidateScorer()
    for query in ['organizing desk workspace', 'clean office desk', 'writing notebook']:
        try:
            candidates = await adapter._fetch_pexels_or_fallback(query, 5, True)
            eligible, rejected = [], []
            for candidate in candidates:
                ok, scored, reasons = scorer.score_candidate(candidate, VisualIntent(scene_id='diagnostic',
                    description=query, search_query_en=query), 4, set(), [], set(), strict_rights=True)
                if ok:
                    eligible.append({'asset_id': scored.asset_id, 'rights': scored.rights_state.value,
                        'score': scored.composite_score, 'score_source': scored.score_source,
                        'duration_sec': scored.duration_sec, 'preview_present': bool(scored.thumbnail_url)})
                else:
                    rejected.extend(reasons)
            eligible.sort(key=lambda c: c['score'], reverse=True)
            print(json.dumps({'query': query, 'provider': 'Pexels live', 'raw_count': len(candidates),
                'eligible_count': len(eligible), 'eligible': eligible, 'selected': eligible[0]['asset_id'] if eligible else None,
                'rejections': rejected, 'scene_library': 'NOT_TESTED', 'production_run_created': False}), flush=True)
        except Exception as exc:
            print(json.dumps({'query': query, 'error_type': type(exc).__name__, 'provider_available': False}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
