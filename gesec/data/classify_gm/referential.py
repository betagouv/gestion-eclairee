"""Chargement du référentiel GM (CSV embarqué dans le package)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from importlib import resources
from io import StringIO
from pathlib import Path

NON_CLASSIFIE = "Non classifié"
_GM_CODE_RE = re.compile(r"^\d+(?:\.\d+)+$")


@dataclass(frozen=True)
class GmEntry:
    code: str
    domaine: str
    segment: str
    libelle: str
    description: str

    def as_prompt_line(self) -> str:
        return f"- {self.code} | {self.domaine} / {self.segment} / {self.libelle} : {self.description.strip()}"


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("latin-1", "cp1252", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _decode_referential(path: Path) -> str:
    return _decode_bytes(path.read_bytes())


def load_referential_rows_from_text(text: str) -> list[dict[str, str]]:
    """Charge Code;Domaine;Segment;Libelle;Description (champs multi-lignes supportés)."""
    reader = csv.DictReader(StringIO(text), delimiter=";")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in reader:
        code = (row.get("Code") or "").strip()
        if not code or code in seen or not _GM_CODE_RE.match(code):
            continue
        seen.add(code)
        rows.append(
            {
                "code": code,
                "domaine": (row.get("Domaine") or "").strip(),
                "segment": (row.get("Segment") or "").strip(),
                "libelle": (row.get("Libelle") or "").strip(),
                "description": (row.get("Description") or "").strip(),
            }
        )
    return rows


def load_referential_rows(path: Path) -> list[dict[str, str]]:
    return load_referential_rows_from_text(_decode_referential(path))


def packaged_gm_ref_path() -> Path:
    """Chemin filesystem vers le gm_ref.csv embarqué (dev / editable install)."""
    return Path(__file__).resolve().parent / "data" / "gm_ref.csv"


def load_packaged_referential_text() -> str:
    """Lit le CSV référentiel embarqué (compatible wheel + editable)."""
    try:
        root = resources.files("gesec.data.classify_gm")
        data = root.joinpath("data", "gm_ref.csv")
        with resources.as_file(data) as path:
            return _decode_referential(Path(path))
    except FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError:
        path = packaged_gm_ref_path()
        if not path.is_file():
            raise FileNotFoundError(f"Référentiel GM introuvable : {path}") from None
        return _decode_referential(path)


def load_referential(path: Path | None = None) -> list[GmEntry]:
    """Charge le référentiel depuis un chemin ou, par défaut, le CSV embarqué."""
    if path is None:
        rows = load_referential_rows_from_text(load_packaged_referential_text())
    else:
        rows = load_referential_rows(path)
    return [GmEntry(**row) for row in rows]


def allowed_gm_codes(entries: list[GmEntry]) -> list[str]:
    return [e.code for e in entries] + [NON_CLASSIFIE]


def domain_code(code: str | None) -> str:
    """Préfixe domaine (ex. 33 depuis 33.02.01)."""
    parts = (code or "").strip().split(".")
    return parts[0] if parts and parts[0] else ""


def segment_code(code: str | None) -> str:
    """Code segment 2e niveau (ex. 33.02 depuis 33.02.01)."""
    parts = (code or "").strip().split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return (code or "").strip()


@dataclass(frozen=True)
class HierarchyNode:
    """Nœud agrégé domaine ou segment pour prompts hiérarchiques."""

    code: str
    libelle: str
    description: str

    def as_prompt_line(self, *, path_libelles: list[str] | None = None) -> str:
        """Affiche code + chemin de libellés depuis la racine (a + b + c)."""
        labels = path_libelles if path_libelles is not None else [self.libelle]
        path = " + ".join(x for x in labels if x)
        desc = self.description.strip()
        if desc:
            return f"- {self.code} | {path} : {desc}"
        return f"- {self.code} | {path}"


def domain_libelle_map(entries: list[GmEntry]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in entries:
        d = domain_code(e.code)
        if d and d not in out:
            out[d] = e.domaine or d
    return out


def segment_libelle_map(entries: list[GmEntry]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in entries:
        s = segment_code(e.code)
        if s and s not in out:
            out[s] = e.segment or s
    return out


def path_libelles_for_code(
    code: str,
    *,
    domain_labels: dict[str, str],
    segment_labels: dict[str, str],
    leaf_libelle: str | None = None,
) -> list[str]:
    """Libellés cumulés racine → feuille pour un code GM."""
    d = domain_code(code)
    s = segment_code(code)
    parts: list[str] = []
    if d:
        parts.append(domain_labels.get(d) or d)
    if s and "." in s:
        parts.append(segment_labels.get(s) or s)
    if leaf_libelle is not None and code.count(".") >= 2:
        parts.append(leaf_libelle)
    return parts


def packaged_gm_enrich_path() -> Path:
    """Chemin filesystem vers gm_ref_enrich.csv (contextes domaine)."""
    return Path(__file__).resolve().parent / "data" / "gm_ref_enrich.csv"


def packaged_gm_enrich_seg_path() -> Path:
    """Chemin filesystem vers gm_ref_enrich_seg.csv (contextes segment)."""
    return Path(__file__).resolve().parent / "data" / "gm_ref_enrich_seg.csv"


def _read_utf8_csv(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")


def _load_enrichment_map(
    *,
    resource_name: str,
    fallback_path: Path,
    path: Path | None = None,
) -> dict[str, str]:
    """Charge Code→Contexte depuis un CSV d'enrichissement UTF-8."""
    if path is None:
        try:
            root = resources.files("gesec.data.classify_gm")
            data = root.joinpath("data", resource_name)
            with resources.as_file(data) as packaged:
                text = _read_utf8_csv(Path(packaged))
        except FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError:
            if not fallback_path.is_file():
                return {}
            text = _read_utf8_csv(fallback_path)
    else:
        text = _read_utf8_csv(path)

    out: dict[str, str] = {}
    reader = csv.DictReader(StringIO(text), delimiter=";")
    for row in reader:
        code = (row.get("Code") or "").strip()
        contexte = (row.get("Contexte") or "").strip()
        if code and contexte:
            out[code] = contexte
    return out


def load_domain_enrichment(path: Path | None = None) -> dict[str, str]:
    """Charge Code→Contexte depuis gm_ref_enrich.csv (embarqué par défaut, UTF-8)."""
    return _load_enrichment_map(
        resource_name="gm_ref_enrich.csv",
        fallback_path=packaged_gm_enrich_path(),
        path=path,
    )


def load_segment_enrichment(path: Path | None = None) -> dict[str, str]:
    """Charge Code→Contexte depuis gm_ref_enrich_seg.csv (embarqué par défaut, UTF-8)."""
    return _load_enrichment_map(
        resource_name="gm_ref_enrich_seg.csv",
        fallback_path=packaged_gm_enrich_seg_path(),
        path=path,
    )


def list_domains(
    entries: list[GmEntry],
    *,
    enrichment: dict[str, str] | None = None,
) -> list[HierarchyNode]:
    """Domaines uniques (préfixe XX), libellé = champ Domaine du référentiel."""
    enrich = enrichment if enrichment is not None else load_domain_enrichment()
    by_code: dict[str, HierarchyNode] = {}
    for e in entries:
        d = domain_code(e.code)
        if not d or d in by_code:
            continue
        by_code[d] = HierarchyNode(
            code=d,
            libelle=e.domaine or d,
            description=enrich.get(d, ""),
        )
    return [by_code[k] for k in sorted(by_code, key=lambda x: [int(p) for p in x.split(".")])]


def list_segments(
    entries: list[GmEntry],
    domain: str,
    *,
    enrichment: dict[str, str] | None = None,
) -> list[HierarchyNode]:
    """Segments XX.YY du domaine donné.

    Par défaut sans contexte segment (ROI faible vs latence). Passer
    ``enrichment`` / ``load_segment_enrichment()`` pour réactiver.
    """
    domain = domain.strip()
    enrich = enrichment if enrichment is not None else {}
    by_code: dict[str, HierarchyNode] = {}
    for e in entries:
        if domain_code(e.code) != domain:
            continue
        s = segment_code(e.code)
        if not s or s in by_code:
            continue
        by_code[s] = HierarchyNode(
            code=s,
            libelle=e.segment or s,
            description=enrich.get(s, ""),
        )
    return [by_code[k] for k in sorted(by_code, key=lambda x: [int(p) for p in x.split(".")])]


def list_leaves(entries: list[GmEntry], segment: str) -> list[GmEntry]:
    """Codes feuille dont le segment 2e niveau = segment."""
    segment = segment.strip()
    return sorted(
        [e for e in entries if segment_code(e.code) == segment],
        key=lambda e: [int(p) for p in e.code.split(".")],
    )


def libelle_lookups(entries: list[GmEntry]) -> tuple[dict[str, str], dict[str, str]]:
    """Maps code→libellé feuille et segment→libellé segment."""
    libelle_by_code = {e.code: e.libelle for e in entries}
    segment_libelle: dict[str, str] = {}
    for e in entries:
        s = segment_code(e.code)
        if s and s not in segment_libelle:
            segment_libelle[s] = e.segment or s
    return libelle_by_code, segment_libelle
