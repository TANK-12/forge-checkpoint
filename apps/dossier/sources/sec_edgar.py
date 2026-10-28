"""SEC EDGAR: what a company or an executive filed, under oath.

The strongest source type in the whole set for business figures. A filing is a
primary document with legal consequences for being wrong, so anything found
here is tiered `primary` and counts heavily toward corroboration. Full-text
search is free and needs no key; the SEC asks only for an identifying
User-Agent, which the fetcher always sends.
"""

from __future__ import annotations

from research.fetcher import Document
from research.scoring import SubjectProfile

from .registry import Context, Harvest, SourceSpec

SEARCH = "https://efts.sec.gov/LATEST/search-index"
VIEWER = "https://www.sec.gov/Archives/edgar/data"

FORM_MEANING = {
    "8-K": "material event",
    "10-K": "annual report",
    "10-Q": "quarterly report",
    "DEF 14A": "proxy statement (pay and board)",
    "4": "insider share dealing",
    "3": "insider holdings",
    "S-1": "registration for public offering",
    "13D": "activist stake",
    "13G": "passive stake",
}


def fetch(subject: SubjectProfile, ctx: Context) -> Harvest:
    harvest = Harvest()
    data = ctx.fetcher.get_json(
        SEARCH,
        api=True,
        params={
            "q": f'"{subject.name}"',
            "forms": "8-K,10-K,DEF 14A,4,S-1",
        },
    )
    hits = (((data or {}).get("hits") or {}).get("hits")) or []
    if not hits:
        harvest.notes.append(f"No SEC filings mention '{subject.name}'")
        ctx.log("SEC EDGAR: no filings")
        return harvest

    for hit in hits[: ctx.budget]:
        src = hit.get("_source") or {}
        form = src.get("file_type") or src.get("root_form") or ""
        filed = src.get("file_date") or ""
        names = src.get("display_names") or []
        filer = names[0] if names else ""
        adsh = (hit.get("_id") or "").split(":")[0].replace("-", "")
        cik = (src.get("ciks") or [""])[0]
        url = (
            f"{VIEWER}/{cik.lstrip('0')}/{adsh}"
            if cik and adsh
            else "https://www.sec.gov/edgar"
        )
        meaning = FORM_MEANING.get(form.upper(), form)
        harvest.documents.append(
            Document(
                url=url,
                title=f"{form} filed by {filer}" if filer else f"{form} filing",
                text=f"SEC form {form} ({meaning}) filed {filed} by {filer}, "
                f"mentioning {subject.name}.",
                published=filed,
                tier="primary",
                origin="sec_edgar",
                domain="sec.gov",
            )
        )
        # Full-text search returns every filing that MENTIONS the name, which
        # for a person is usually a fund or an unrelated filer quoting them in
        # passing. Only a filing by the subject itself belongs on their
        # timeline; the rest stay as documents and are scored like anything
        # else, rather than arriving pre-stamped as verified events.
        about_subject = (
            ctx.entity_type == "organisation"
            or subject.surname.lower() in (filer or "").lower()
        )
        if filed and about_subject:
            harvest.timeline.append(
                {
                    "date": filed,
                    "end": "",
                    "title": f"{form}: {filer}".strip(": "),
                    "kind": "filing",
                    "detail": f"SEC {form} - {meaning}",
                    "source_id": "sec_edgar",
                    "url": url,
                    "confidence": "verified",
                }
            )
    ctx.log(f"SEC EDGAR: {len(harvest.documents)} filings")
    return harvest


SPEC = SourceSpec(
    name="sec_edgar",
    label="SEC EDGAR",
    tier="primary",
    phases=("quick", "deep"),
    entity_types=("organisation", "person"),
    fetch=fetch,
    description="US securities filings - primary documents with legal weight.",
)
