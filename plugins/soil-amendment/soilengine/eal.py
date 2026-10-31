"""Reader for EAL (Environmental Analysis Laboratory, SCU Lismore) Certificate of Analysis CSVs.

Real EAL CoAs arrive in two layouts. Both are handled here.

Layout A - newer, keyed on an internal Report ID:
    Report ID,E25-00-0021_EALP1_1,,,,,
    Client Sample ID:,,,,Leaf Block 1,Leaf Block 2
    ...
    Parameter,Unit,Method Reference,LOR,---,---
    Total Carbon,%,Inhouse S4a,<0.02,46.8,46.4

Layout B - older, method-first, one sample per file, no Report ID:
    Client Sample ID:,,,,Cells 1 to 8
    ...
    Method Reference,Parameter,Unit,LOR,E24-00-0573-0001
    ** Inhouse S10 - Morgan,Soluble Calcium,mg/kg,<10,1840

Two things that bite:
  * Parameter names repeat within a file. The unit is what disambiguates:
    ('Exchangeable Calcium','cmol+/kg') is the Albrecht figure, while
    ('Calcium','%') is the calculated base saturation and ('Calcium','mg/kg')
    is the total acid extractable reserve. Keys are therefore (name, unit).
  * Below-LOR results are returned as "<10" / "< 0.5". These are NOT numeric
    zero. They are preserved as status='below_lor' with the LOR recorded, and
    callers decide what to do with them.
"""
from __future__ import annotations

import csv
import itertools
import math
import os
import re
from dataclasses import dataclass, field

REPORT_ID_RE = re.compile(r"(E\d{2}-\d{2}-\d{4})_([A-Z]+\d+)_(\d+)")
NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
LESS_THAN_RE = re.compile(r"^<\s*([\d.]+)$")

# Values that mean "no result" rather than zero.
NULLISH = {"", "---", "n/a", "na", "nd", "nil", "-"}

#: The largest reading a soil or plant test can plausibly report. `float("9"*400)` is an infinity
#: rather than an exception, and an infinity in a deficit becomes an infinity in a rate
#: (the internal security audit A19-PLUG-5, A19-PLUG-6).
MAX_READING = 1e9

#: What this reader will take from one certificate of analysis. A real EAL CoA is a handful of
#: samples and a few dozen parameter rows; the audit's crafted file was 4.4 MB with 40,000 value
#: columns, because the reader materialised the whole CSV and the tool ran a full recommendation
#: for every column — a 226 MB tool result (the internal security audit A19-PLUG-7). The caps
#: live here, at the reader, so no caller can be handed the unbounded thing.
MAX_SAMPLES = 50
MAX_ROWS = 2000
MAX_BYTES = 16 * 1024 * 1024


class CoATooLarge(ValueError):
    """A certificate of analysis beyond what this reader will take, naming the count."""


@dataclass
class Result:
    """One parameter result for one sample."""
    parameter: str
    unit: str
    method: str
    lor: str
    raw: str
    value: float | None
    status: str  # 'ok' | 'below_lor' | 'missing' | 'unreadable'

    @property
    def key(self) -> tuple[str, str]:
        return (self.parameter, self.unit)


@dataclass
class Sample:
    """One sample column from a CoA."""
    index: int
    sample_id: str
    eal_sample_id: str | None
    meta: dict[str, str]
    results: dict[tuple[str, str], Result] = field(default_factory=dict)

    def get(self, parameter: str, unit: str | None = None) -> Result | None:
        """Fetch by parameter name. If unit is None, accept a unique name match."""
        if unit is not None:
            return self.results.get((parameter, unit))
        hits = [r for (p, _), r in self.results.items() if p == parameter]
        if len(hits) == 1:
            return hits[0]
        return None

    def value(self, parameter: str, unit: str | None = None, default=None):
        """Numeric value, or `default` when missing / below LOR."""
        r = self.get(parameter, unit)
        if r is None or r.status == "missing":
            return default
        if r.status == "below_lor":
            return default
        return r.value

    def value_or_lor_half(self, parameter: str, unit: str | None = None, default=None):
        """Numeric value, substituting LOR/2 for below-LOR results.

        Used for base-saturation arithmetic, where ignoring a below-LOR trace
        would silently bias the balance.
        """
        r = self.get(parameter, unit)
        if r is None or r.status == "missing":
            return default
        if r.status == "below_lor":
            # The cell's own `<5` when it had one, else the LOR column: either way the limit of
            # reporting, halved.
            lo = r.lor.strip("\u200b ").lstrip("<").strip()
            try:
                return float(lo) / 2.0
            except ValueError:
                return default
        return r.value


@dataclass
class CoA:
    """A parsed EAL Certificate of Analysis."""
    path: str
    report_id: str | None
    job: str | None
    pack_code: str | None
    pack_version: str | None
    test_type: str  # 'soil' | 'plant' | 'unknown'
    samples: list[Sample]
    warnings: list[str] = field(default_factory=list)


def _cell_int(meta: dict[str, str]) -> dict[str, str]:  # pragma: no cover
    return meta


#: `1,234` / `1,234.5` — a comma used as a thousands separator.
THOUSANDS_RE = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
#: `1,5` — a comma used as a decimal point, which is how half of Europe writes a number.
DECIMAL_COMMA_RE = re.compile(r"^\d+,\d+$")


def _parse_value(raw: str) -> tuple[float | None, str]:
    """Return (value, status) for a raw CoA cell.

    A comma is read as a thousands separator *only* against the thousands pattern. It used to be
    stripped unconditionally, so `"1,5"` became `15.0` and `"12,50"` became `1250.0` — a 10–100×
    error with status "ok", on a number every rate downstream depends on. A decimal comma is
    read as a decimal point; anything else with a comma in it is `unreadable` and named in the
    parse warnings rather than silently guessed at (the internal audit PLUG-10).
    """
    s = (raw or "").strip().replace("\u200b", "")
    if s.lower() in NULLISH:
        return None, "missing"
    if LESS_THAN_RE.match(s):
        # Still not a measurement: `value` stays None. What the cell *does* carry is the limit of
        # reporting, and the row parse keeps it (see `lor` below) — it used to be thrown away in
        # favour of the separate LOR column, so an empty LOR column left no LOR/2 to substitute
        # at all and a disagreeing one substituted a different magnitude
        # (the internal audit PLUG-10).
        return None, "below_lor"
    if THOUSANDS_RE.match(s):
        return float(s.replace(",", "")), "ok"
    if DECIMAL_COMMA_RE.match(s):
        return float(s.replace(",", ".")), "ok"
    if NUM_RE.match(s):
        value = float(s)
        if value < 0 or not math.isfinite(value) or value > MAX_READING:
            # A negative concentration is not a measurement. The audit's crafted `-999999` cell
            # produced a 1,000,069 ppm deficit and a 25,001,725 kg/ha recommendation, because
            # `soil.py` computes `max(0.0, ideal - actual)` and cannot see the sign
            # (the internal security audit A19-PLUG-6). It is unreadable, like a comma that
            # is neither separator nor decimal, and the parse warnings name it. An infinity from a
            # 400-digit cell is the same shape and is refused with it (A19-PLUG-5).
            return None, "unreadable"
        return value, "ok"
    if "," in s:
        return None, "unreadable"
    return None, "missing"


def _unreadable_reason(cell: str) -> str:
    """Why a cell was not read, in the words the parse warning carries."""
    if cell.startswith("-"):
        return "a negative reading is not a measurement"
    if NUM_RE.match(cell):
        return "it is larger than any reading a laboratory reports"
    return "a comma that is neither a thousands separator nor a decimal comma"


def read_coa(path: str) -> CoA:
    """Parse an EAL CoA CSV into a CoA object, or refuse one too large to be one."""
    name = os.path.basename(path)
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ValueError(f"{name}: {exc.strerror or exc}") from exc
    if size > MAX_BYTES:
        raise CoATooLarge(
            f"{name} is {size / 1_000_000:.1f} MB, more than the {MAX_BYTES // 1_000_000} MB this "
            f"reader will take from one certificate of analysis"
        )
    # Rows are streamed to the cap rather than materialised: the whole file in memory was half of
    # the audit's finding (the internal security audit A19-PLUG-7).
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        rows = list(itertools.islice(csv.reader(fh), MAX_ROWS + 1))
    if len(rows) > MAX_ROWS:
        raise CoATooLarge(
            f"{name} has more than {MAX_ROWS} rows, which is more than one certificate of "
            f"analysis carries"
        )
    if not rows:
        raise ValueError(f"empty file: {name}")

    warnings: list[str] = []

    # ---- locate header row ------------------------------------------------
    hdr_idx = None
    pcol = ucol = lcol = None
    for i, r in enumerate(rows[:15]):
        lowered = [c.strip().lower() for c in r[:4]]
        if "parameter" in lowered and "unit" in lowered:
            hdr_idx = i
            pcol = lowered.index("parameter")
            ucol = lowered.index("unit")
            lcol = lowered.index("lor") if "lor" in lowered else ucol + 1
            break
    if hdr_idx is None:
        raise ValueError(f"{name}: could not find a Parameter/Unit header row")

    header = rows[hdr_idx]
    mcol = lowered_m = None
    lowered_hdr = [c.strip().lower() for c in header]
    if "method reference" in lowered_hdr:
        mcol = lowered_hdr.index("method reference")

    vcol_start = max(pcol, ucol, lcol, (mcol if mcol is not None else 0)) + 1
    # value columns = the rest, but Layout A pads with '---' placeholders that
    # still align to real sample columns, so take everything from vcol_start on.
    value_cols = list(range(vcol_start, len(header)))
    if len(value_cols) > MAX_SAMPLES:
        raise CoATooLarge(
            f"{name} has {len(value_cols)} sample columns, more than the {MAX_SAMPLES} this "
            f"reader will take from one certificate of analysis — is this really one certificate?"
        )

    # ---- metadata rows (everything above the header) ----------------------
    meta_rows: list[list[str]] = rows[:hdr_idx]
    report_id = job = pack = ver = None
    for r in meta_rows:
        joined = ",".join(r)
        m = REPORT_ID_RE.search(joined)
        if m and report_id is None:
            job, pack, ver = m.group(1), m.group(2), m.group(3)
            report_id = f"{job}_{pack}_{ver}"
        if r and r[0].strip().lower().startswith("report id") and len(r) > 1 and r[1].strip():
            m2 = REPORT_ID_RE.match(r[1].strip())
            if m2:
                job, pack, ver = m2.group(1), m2.group(2), m2.group(3)
                report_id = f"{job}_{pack}_{ver}"

    def meta_for(col: int) -> dict[str, str]:
        out = {}
        for r in meta_rows:
            if not r:
                continue
            label = r[0].strip().rstrip(":").strip()
            if not label:
                continue
            val = ""
            if col < len(r) and r[col].strip():
                val = r[col].strip()
            else:  # Layout B: single sample, value may sit in the last cell
                tail = [c for c in r[1:] if c.strip()]
                if len(tail) == 1:
                    val = tail[0].strip()
            if val:
                out[label] = val
        return out

    # ---- build samples ----------------------------------------------------
    samples: list[Sample] = []
    n_samples = len(value_cols)
    for n, col in enumerate(value_cols):
        meta = meta_for(col)
        sid = (meta.get("Client Sample ID") or meta.get("Sample Description #1")
               or meta.get("EAL Sample ID") or f"sample-{n+1}")
        samples.append(Sample(
            index=n,
            sample_id=sid,
            eal_sample_id=meta.get("EAL Sample ID"),
            meta=meta,
        ))

    # ---- data rows --------------------------------------------------------
    for r in rows[hdr_idx + 1:]:
        if not any(c.strip() for c in r):
            continue
        if pcol >= len(r):
            continue
        param = r[pcol].strip()
        if not param:
            continue
        unit = r[ucol].strip() if ucol < len(r) else ""
        method = r[mcol].strip() if (mcol is not None and mcol < len(r)) else ""
        lor = r[lcol].strip() if lcol < len(r) else ""
        for n, col in enumerate(value_cols):
            raw = r[col] if col < len(r) else ""
            val, status = _parse_value(raw)
            if status == "below_lor" and raw.strip().startswith("<"):
                # The cell's own limit beats the column: `<0.1` is this parameter's limit, and
                # the LOR column may be empty or describe a different row.
                lor = raw.strip()
            res = Result(parameter=param, unit=unit, method=method, lor=lor,
                         raw=raw.strip(), value=val, status=status)
            if status == "unreadable":
                warnings.append(
                    f"{name} sample {n+1}: could not read {param!r} from {raw.strip()!r} — "
                    f"{_unreadable_reason(raw.strip())}; the value is treated as missing"
                )
            if res.key in samples[n].results:
                warnings.append(
                    f"{name} sample {n+1}: duplicate key {res.key} "
                    f"(kept the later row, method '{method}')")
            samples[n].results[res.key] = res

    # ---- test type --------------------------------------------------------
    names = {p for s in samples for (p, _) in s.results}
    if "Exchangeable Calcium" in names or "Total Cation Exchange Capacity" in names:
        test_type = "soil"
    # Grouped as intended: a plant tissue panel is protein *or* carbon-plus-nitrogen. The
    # `and` bound tighter than the `or` here, and the trailing clause could never have changed
    # the outcome — the soil branch above has already taken every sample with exchangeable
    # calcium (the internal audit PLUG-16).
    elif (
        "Crude Protein" in names
        or ("Total Carbon" in names and "Total Nitrogen" in names)
    ):
        test_type = "plant"
    else:
        test_type = "unknown"
        warnings.append(f"{name}: could not classify test type")

    if not report_id:
        warnings.append(f"{name}: no internal Report ID found (probably renamed on save)")

    return CoA(path=path, report_id=report_id, job=job, pack_code=pack,
               pack_version=ver, test_type=test_type, samples=samples,
               warnings=warnings)
