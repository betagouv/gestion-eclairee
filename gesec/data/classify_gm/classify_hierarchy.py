"""Classification GM hiérarchique : domaine → segment → feuille (3 appels LLM)."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

from tqdm import tqdm

from gesec.data.classify_gm.classify import (
    DEFAULT_MAX_WORKERS,
    ClassifyMode,
    FactureSample,
    sample_factures,
    upsert_prediction,
)
from gesec.data.classify_gm.prompt import parse_llm_content
from gesec.data.classify_gm.prompt_hierarchy import (
    SYSTEM_PROMPT_HIERARCHY,
    build_domain_user_prompt,
    build_label_maps,
    build_leaf_user_prompt,
    build_segment_user_prompt,
    response_format_choice,
)
from gesec.data.classify_gm.referential import (
    NON_CLASSIFIE,
    list_domains,
    list_leaves,
    list_segments,
    load_domain_enrichment,
    load_referential,
    load_segment_enrichment,
)

logger = logging.getLogger(__name__)


def classify_facture_hierarchical(
    llm_client,
    sample: FactureSample,
    entries,
    model: str,
    *,
    domain_enrichment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """3 appels séquentiels (domaine → segment → feuille) avec segenrich."""
    t_total0 = time.perf_counter()
    timings: dict[str, float] = {}
    raw_steps: dict[str, Any] = {}
    domain_labels, segment_labels = build_label_maps(entries)
    enrichment = domain_enrichment if domain_enrichment is not None else load_domain_enrichment()
    segment_enrichment = load_segment_enrichment()

    domains = list_domains(entries, enrichment=enrichment)
    domain_codes = [d.code for d in domains] + [NON_CLASSIFIE]

    t0 = time.perf_counter()
    r1 = llm_client.ask_llm(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_HIERARCHY},
            {
                "role": "user",
                "content": build_domain_user_prompt(
                    fournisseur_designation=sample.fournisseur_designation,
                    mt_ttc=sample.mt_ttc,
                    lignes=sample.lignes,
                    domains=domains,
                ),
            },
        ],
        model=model,
        response_format=response_format_choice("domaine", domain_codes),
        temperature=0.0,
    )
    timings["domaine_s"] = round(time.perf_counter() - t0, 3)
    p1 = parse_llm_content(r1.content)
    domaine = (p1.get("domaine") or "").strip() or NON_CLASSIFIE
    if domaine not in domain_codes:
        domaine = NON_CLASSIFIE
    domain_libelle = domain_labels.get(domaine, domaine)
    domain_contexte = enrichment.get(domaine, "")
    raw_steps["domaine"] = {
        "choice": domaine,
        "libelle": domain_libelle,
        "raison": p1.get("raison") or "",
    }

    if domaine == NON_CLASSIFIE:
        total_s = round(time.perf_counter() - t_total0, 3)
        return {
            "gm_pred": NON_CLASSIFIE,
            "raison": raw_steps["domaine"]["raison"],
            "domaine": domaine,
            "segment": None,
            "raw": {"steps": raw_steps, "timings": {**timings, "total_s": total_s}},
            "latency_s": total_s,
        }

    segments = list_segments(entries, domaine, enrichment=segment_enrichment)
    if not segments:
        total_s = round(time.perf_counter() - t_total0, 3)
        return {
            "gm_pred": NON_CLASSIFIE,
            "raison": f"Aucun segment pour domaine {domaine}",
            "domaine": domaine,
            "segment": None,
            "raw": {"steps": raw_steps, "timings": {**timings, "total_s": total_s}},
            "latency_s": total_s,
        }

    segment_codes = [s.code for s in segments] + [NON_CLASSIFIE]
    t0 = time.perf_counter()
    r2 = llm_client.ask_llm(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_HIERARCHY},
            {
                "role": "user",
                "content": build_segment_user_prompt(
                    fournisseur_designation=sample.fournisseur_designation,
                    mt_ttc=sample.mt_ttc,
                    lignes=sample.lignes,
                    domain=domaine,
                    domain_libelle=domain_libelle,
                    segments=segments,
                    domain_contexte=domain_contexte,
                ),
            },
        ],
        model=model,
        response_format=response_format_choice("segment", segment_codes),
        temperature=0.0,
    )
    timings["segment_s"] = round(time.perf_counter() - t0, 3)
    p2 = parse_llm_content(r2.content)
    segment = (p2.get("segment") or "").strip() or NON_CLASSIFIE
    if segment not in segment_codes:
        segment = NON_CLASSIFIE
    segment_libelle = segment_labels.get(segment, segment)
    raw_steps["segment"] = {
        "choice": segment,
        "libelle": segment_libelle,
        "raison": p2.get("raison") or "",
    }

    if segment == NON_CLASSIFIE:
        total_s = round(time.perf_counter() - t_total0, 3)
        return {
            "gm_pred": NON_CLASSIFIE,
            "raison": raw_steps["segment"]["raison"],
            "domaine": domaine,
            "segment": segment,
            "raw": {"steps": raw_steps, "timings": {**timings, "total_s": total_s}},
            "latency_s": total_s,
        }

    leaves = list_leaves(entries, segment)
    if not leaves:
        total_s = round(time.perf_counter() - t_total0, 3)
        return {
            "gm_pred": NON_CLASSIFIE,
            "raison": f"Aucune feuille pour segment {segment}",
            "domaine": domaine,
            "segment": segment,
            "raw": {"steps": raw_steps, "timings": {**timings, "total_s": total_s}},
            "latency_s": total_s,
        }

    leaf_codes = [e.code for e in leaves] + [NON_CLASSIFIE]
    t0 = time.perf_counter()
    r3 = llm_client.ask_llm(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_HIERARCHY},
            {
                "role": "user",
                "content": build_leaf_user_prompt(
                    fournisseur_designation=sample.fournisseur_designation,
                    mt_ttc=sample.mt_ttc,
                    lignes=sample.lignes,
                    domain=domaine,
                    domain_libelle=domain_libelle,
                    segment=segment,
                    segment_libelle=segment_libelle,
                    leaves=leaves,
                    domain_contexte=domain_contexte,
                ),
            },
        ],
        model=model,
        response_format=response_format_choice("gm_pred", leaf_codes),
        temperature=0.0,
    )
    timings["leaf_s"] = round(time.perf_counter() - t0, 3)
    p3 = parse_llm_content(r3.content)
    gm_pred = (p3.get("gm_pred") or "").strip() or NON_CLASSIFIE
    if gm_pred not in leaf_codes:
        gm_pred = NON_CLASSIFIE
    raw_steps["leaf"] = {"choice": gm_pred, "raison": p3.get("raison") or ""}

    total_s = round(time.perf_counter() - t_total0, 3)
    raison = (
        f"[dom={domaine}] {raw_steps['domaine']['raison']} | "
        f"[seg={segment}] {raw_steps['segment']['raison']} | "
        f"[leaf] {raw_steps['leaf']['raison']}"
    )
    return {
        "gm_pred": gm_pred,
        "raison": raison,
        "domaine": domaine,
        "segment": segment,
        "raw": {"steps": raw_steps, "timings": {**timings, "total_s": total_s}},
        "latency_s": total_s,
    }


def run_classify_hierarchical(
    conn,
    llm_client,
    *,
    n: int = 100,
    seed: int | None = 42,
    model: str,
    mode: ClassifyMode = "new",
    identifiants: list[str] | None = None,
    exclude_fournisseurs: list[str] | None = None,
    require_gm: bool = False,
    ministere: str | None = None,
    date_min: date | None = None,
    date_max: date | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    referential_path: Path | None = None,
) -> list[dict[str, Any]]:
    entries = load_referential(referential_path)
    if not entries:
        raise RuntimeError("Référentiel GM vide")
    enrichment = load_domain_enrichment()

    samples = sample_factures(
        conn,
        n=n,
        seed=seed,
        mode=mode,
        identifiants=identifiants,
        exclude_fournisseurs=exclude_fournisseurs,
        require_gm=require_gm,
        ministere=ministere,
        date_min=date_min,
        date_max=date_max,
    )
    logger.info(
        "Classification hiérarchique de %s factures (model=%s, mode=%s, ministere=%s, workers=%s)",
        len(samples),
        model,
        mode,
        ministere,
        max_workers,
    )
    if not samples:
        return []

    results: list[dict[str, Any]] = []

    def classify_one(sample: FactureSample):
        try:
            prediction = classify_facture_hierarchical(
                llm_client,
                sample,
                entries,
                model=model,
                domain_enrichment=enrichment,
            )
            return sample, prediction, None
        except Exception as exc:  # noqa: BLE001
            logger.exception("Erreur classification hier %s", sample.identifiant_chorus_pro)
            return sample, None, str(exc)

    workers = max(1, max_workers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(classify_one, sample) for sample in samples]
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc=f"Classification GM hier [{mode}]",
            unit="facture",
        ):
            sample, prediction, error = future.result()
            if error is not None:
                results.append(
                    {
                        "identifiant_chorus_pro": sample.identifiant_chorus_pro,
                        "gm": sample.gm,
                        "gm_pred": None,
                        "error": error,
                        "latency_s": None,
                    }
                )
                continue
            assert prediction is not None
            upsert_prediction(
                conn,
                identifiant_chorus_pro=sample.identifiant_chorus_pro,
                gm_pred=prediction["gm_pred"],
                domaine=prediction.get("domaine"),
                segment=prediction.get("segment"),
                raison=prediction["raison"],
                raw=prediction["raw"],
                model=model,
                latency_s=prediction.get("latency_s"),
            )
            results.append(
                {
                    "identifiant_chorus_pro": sample.identifiant_chorus_pro,
                    "gm": sample.gm,
                    "gm_pred": prediction["gm_pred"],
                    "domaine": prediction.get("domaine"),
                    "segment": prediction.get("segment"),
                    "latency_s": prediction.get("latency_s"),
                    "error": None,
                }
            )
    return results
